import {
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  CfnOutput,
  aws_cloudfront as cloudfront,
  aws_cloudfront_origins as origins,
  aws_cloudwatch as cloudwatch,
  aws_cloudwatch_actions as cloudwatch_actions,
  aws_dynamodb as dynamodb,
  aws_iam as iam,
  aws_lambda as lambda,
  aws_lambda_event_sources as lambda_events,
  aws_s3 as s3,
  aws_scheduler as scheduler,
  aws_ses as ses,
  aws_sns as sns,
  aws_sqs as sqs,
} from "aws-cdk-lib";
import { Construct } from "constructs";

export interface StockAnalysisInfraStackProps extends StackProps {
  envName: string;
  reportEmailAddress?: string;
  // ARN of the pre-published Lambda layer containing yfinance + pandas + numpy + google-generativeai.
  // Publish once via: aws lambda publish-layer-version --layer-name dev-stock-analysis-deps ...
  // Then pass the returned LayerVersionArn here (or update to a new version as deps change).
  depsLayerArn: string;
}

export class StockAnalysisInfraStack extends Stack {
  constructor(scope: Construct, id: string, props: StockAnalysisInfraStackProps) {
    super(scope, id, props);

    // ------------------------------------------------------------------ //
    // Storage                                                              //
    // ------------------------------------------------------------------ //

    const cacheBucket = new s3.Bucket(this, "MarketDataBucket", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // ------------------------------------------------------------------ //
    // CloudFront                                                           //
    // ------------------------------------------------------------------ //

    const originAccessIdentity = new cloudfront.OriginAccessIdentity(
      this, "ReportOriginAccessIdentity"
    );
    cacheBucket.grantRead(originAccessIdentity);

    const reportDistribution = new cloudfront.Distribution(this, "ReportDistribution", {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessIdentity(cacheBucket, {
          originAccessIdentity,
        }),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
      },
      defaultRootObject: "index.html",
    });

    // ------------------------------------------------------------------ //
    // DynamoDB metadata tables                                             //
    // ------------------------------------------------------------------ //

    const createMetadataTable = (
      id: string, tableName: string, partitionKey: string, sortKey: string
    ) =>
      new dynamodb.Table(this, id, {
        tableName: `${props.envName}-${tableName}`,
        partitionKey: { name: partitionKey, type: dynamodb.AttributeType.STRING },
        sortKey: { name: sortKey, type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
        removalPolicy: RemovalPolicy.RETAIN,
      });

    const watchlistsTable    = createMetadataTable("WatchlistsTable",    "watchlists",    "watchlistId",    "version");
    const rulesTable         = createMetadataTable("RulesTable",         "rules",         "ruleId",         "version");
    const runsTable          = createMetadataTable("RunsTable",          "runs",          "runId",          "artifact");
    const notificationsTable = createMetadataTable("NotificationsTable", "notifications", "notificationId", "timestamp");

    // ------------------------------------------------------------------ //
    // SQS                                                                  //
    // ------------------------------------------------------------------ //

    const workerDlq = new sqs.Queue(this, "WorkerDLQ", {
      retentionPeriod: Duration.days(14),
    });

    const workerQueue = new sqs.Queue(this, "WorkerQueue", {
      visibilityTimeout: Duration.minutes(15),
      deadLetterQueue: { queue: workerDlq, maxReceiveCount: 3 },
    });

    // ------------------------------------------------------------------ //
    // IAM role shared by all Lambda functions                             //
    // ------------------------------------------------------------------ //

    const lambdaRole = new iam.Role(this, "LambdaExecutionRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    });
    cacheBucket.grantReadWrite(lambdaRole);
    workerQueue.grantSendMessages(lambdaRole);
    workerQueue.grantConsumeMessages(lambdaRole);
    watchlistsTable.grantReadData(lambdaRole);
    rulesTable.grantReadData(lambdaRole);
    runsTable.grantReadWriteData(lambdaRole);
    notificationsTable.grantReadWriteData(lambdaRole);

    // Allow the aggregator to invalidate CloudFront after publishing the report.
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ["cloudfront:CreateInvalidation"],
      resources: [`arn:aws:cloudfront::${this.account}:distribution/${reportDistribution.distributionId}`],
    }));

    // Allow the aggregator to read the Gemini API key from Secrets Manager.
    // The secret is managed externally via scripts/manage-gemini-key.sh.
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ["secretsmanager:GetSecretValue"],
      resources: [
        `arn:aws:secretsmanager:${this.region}:${this.account}:secret:stock-analysis/gemini-api-key-*`,
        `arn:aws:secretsmanager:${this.region}:${this.account}:secret:stock-analysis/earnings-api-key-*`,
      ],
    }));

    // ------------------------------------------------------------------ //
    // Lambda layer — yfinance, pandas, numpy, google-generativeai (pre-built, published once) //
    // ------------------------------------------------------------------ //

    const depsLayer = lambda.LayerVersion.fromLayerVersionArn(
      this, "DepsLayer", props.depsLayerArn
    );

    // ------------------------------------------------------------------ //
    // Shared Lambda config                                                 //
    // ------------------------------------------------------------------ //

    // Zip the app/ directory — no Docker required.
    const appCode = lambda.Code.fromAsset("../app");

    const sharedEnv = {
      ENV_NAME: props.envName,
      CACHE_BUCKET: cacheBucket.bucketName,
    };

    const sharedFnProps = {
      runtime: lambda.Runtime.PYTHON_3_11,
      code: appCode,
      role: lambdaRole,
      layers: [depsLayer],
    };

    // ------------------------------------------------------------------ //
    // Lambda functions                                                     //
    // ------------------------------------------------------------------ //

    const coordinatorFn = new lambda.Function(this, "CoordinatorFunction", {
      ...sharedFnProps,
      handler: "stock_analysis.handlers.coordinator.handler",
      timeout: Duration.minutes(5),
      memorySize: 512,
      environment: {
        ...sharedEnv,
        WORKER_QUEUE_URL: workerQueue.queueUrl,
      },
    });

    const workerFn = new lambda.Function(this, "WorkerFunction", {
      ...sharedFnProps,
      handler: "stock_analysis.handlers.worker.handler",
      timeout: Duration.minutes(15),
      memorySize: 1024,   // yfinance + pandas are memory-hungry
      environment: {
        ...sharedEnv,
        EARNINGS_API_SECRET_NAME: "stock-analysis/earnings-api-key",
      },
    });

    const aggregatorFn = new lambda.Function(this, "AggregatorFunction", {
      ...sharedFnProps,
      handler: "stock_analysis.handlers.aggregator.handler",
      timeout: Duration.minutes(5),
      memorySize: 512,
      environment: {
        ...sharedEnv,
        CLOUDFRONT_DISTRIBUTION_ID: reportDistribution.distributionId,
        GEMINI_SECRET_NAME: "stock-analysis/gemini-api-key",
      },
    });

    // Worker consumes from SQS (one chunk per invocation)
    workerFn.addEventSource(new lambda_events.SqsEventSource(workerQueue, {
      batchSize: 1,
    }));

    // ------------------------------------------------------------------ //
    // EventBridge Scheduler                                                //
    // ------------------------------------------------------------------ //

    const schedulerRole = new iam.Role(this, "NightlySchedulerRole", {
      assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com"),
    });
    schedulerRole.addToPolicy(new iam.PolicyStatement({
      actions: ["lambda:InvokeFunction"],
      resources: [coordinatorFn.functionArn, aggregatorFn.functionArn],
    }));

    // 5:00 PM PT — coordinator fans out work to SQS → workers run in parallel
    new scheduler.CfnSchedule(this, "NightlyCoordinatorSchedule", {
      name: `${props.envName}-nightly-coordinator`,
      flexibleTimeWindow: { mode: "OFF" },
      scheduleExpression: "cron(0 17 ? * MON-FRI *)",
      scheduleExpressionTimezone: "America/Los_Angeles",
      target: {
        arn: coordinatorFn.functionArn,
        roleArn: schedulerRole.roleArn,
        input: JSON.stringify({ run_type: "nightly", env_name: props.envName }),
      },
    });

    // 5:10 PM PT — aggregator collects finished chunk results and publishes report.
    // Workers finish in <5 min; 10-min gap is a sufficient safety buffer.
    new scheduler.CfnSchedule(this, "NightlyAggregatorSchedule", {
      name: `${props.envName}-nightly-aggregator`,
      flexibleTimeWindow: { mode: "OFF" },
      scheduleExpression: "cron(10 17 ? * MON-FRI *)",
      scheduleExpressionTimezone: "America/Los_Angeles",
      target: {
        arn: aggregatorFn.functionArn,
        roleArn: schedulerRole.roleArn,
        input: JSON.stringify({ run_type: "nightly", env_name: props.envName }),
      },
    });

    // ------------------------------------------------------------------ //
    // CloudWatch alarms                                                   //
    // ------------------------------------------------------------------ //

    const alarmTopic = new sns.Topic(this, "AlarmTopic", {
      topicName: `${props.envName}-stock-analysis-alarms`,
      displayName: "Stock Analysis Nightly Run Alarms",
    });

    const alarmAction = new cloudwatch_actions.SnsAction(alarmTopic);

    const coordinatorErrorAlarm = new cloudwatch.Alarm(this, "CoordinatorErrorAlarm", {
      metric: coordinatorFn.metricErrors({
        period: Duration.minutes(5),
        statistic: "Sum",
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmName: `${props.envName}-coordinator-errors`,
      alarmDescription: "Coordinator Lambda failed — nightly run may not have fanned out",
    });
    coordinatorErrorAlarm.addAlarmAction(alarmAction);

    const aggregatorErrorAlarm = new cloudwatch.Alarm(this, "AggregatorErrorAlarm", {
      metric: aggregatorFn.metricErrors({
        period: Duration.minutes(5),
        statistic: "Sum",
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmName: `${props.envName}-aggregator-errors`,
      alarmDescription: "Aggregator Lambda failed — report may not have been published",
    });
    aggregatorErrorAlarm.addAlarmAction(alarmAction);

    const dlqDepthAlarm = new cloudwatch.Alarm(this, "WorkerDLQDepthAlarm", {
      metric: workerDlq.metricApproximateNumberOfMessagesVisible({
        period: Duration.minutes(5),
        statistic: "Maximum",
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmName: `${props.envName}-worker-dlq-depth`,
      alarmDescription: "Messages stuck in worker DLQ — one or more ticker chunks failed",
    });
    dlqDepthAlarm.addAlarmAction(alarmAction);

    // ------------------------------------------------------------------ //
    // Optional SES identity for email delivery                            //
    // ------------------------------------------------------------------ //

    if (props.reportEmailAddress) {
      new ses.CfnEmailIdentity(this, "ReportEmailIdentity", {
        emailIdentity: props.reportEmailAddress,
      });
    }

    // ------------------------------------------------------------------ //
    // Outputs                                                              //
    // ------------------------------------------------------------------ //

    new CfnOutput(this, "ReportUrl", {
      value: `https://${reportDistribution.domainName}`,
      description: "CloudFront URL for the nightly report dashboard",
    });

    new CfnOutput(this, "CacheBucketName", {
      value: cacheBucket.bucketName,
      description: "S3 bucket for market data cache and report hosting",
    });

    new CfnOutput(this, "CoordinatorFunctionName", {
      value: coordinatorFn.functionName,
      description: "Coordinator Lambda (for manual triggers)",
    });

    new CfnOutput(this, "AggregatorFunctionName", {
      value: aggregatorFn.functionName,
      description: "Aggregator Lambda (for manual triggers)",
    });

    new CfnOutput(this, "AlarmTopicArn", {
      value: alarmTopic.topicArn,
      description: "SNS topic for nightly run alarms — subscribe an email to receive alerts",
    });
  }
}
