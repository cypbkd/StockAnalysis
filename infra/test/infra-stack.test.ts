import { App } from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { StockAnalysisInfraStack } from "../lib/stock-analysis-infra-stack";

describe("StockAnalysisInfraStack", () => {
  const app = new App();
  const stack = new StockAnalysisInfraStack(app, "TestStack", {
    envName: "dev",
    reportEmailAddress: "reports@example.com",
    depsLayerArn: "arn:aws:lambda:us-west-2:123456789012:layer:dev-stock-analysis-deps:1",
  });
  const template = Template.fromStack(stack);

  it("creates the cached data and report bucket", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          {
            ServerSideEncryptionByDefault: {
              SSEAlgorithm: "AES256"
            }
          }
        ]
      }
    });
    template.resourceCountIs("AWS::S3::Bucket", 1);
  });

  it("creates cloudfront distribution for the static report site", () => {
    template.resourceCountIs("AWS::CloudFront::Distribution", 1);
  });

  it("creates the metadata table", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      BillingMode: "PAY_PER_REQUEST",
      PointInTimeRecoverySpecification: {
        PointInTimeRecoveryEnabled: true
      }
    });
    template.resourceCountIs("AWS::DynamoDB::Table", 4);
  });

  it("creates the SQS worker queue with a dead-letter queue", () => {
    template.resourceCountIs("AWS::SQS::Queue", 2);
    template.hasResourceProperties("AWS::SQS::Queue", {
      VisibilityTimeout: 900
    });
  });

  it("creates the coordinator, worker, and aggregator Lambda functions", () => {
    template.resourceCountIs("AWS::Lambda::Function", 3);
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "stock_analysis.handlers.coordinator.handler",
      Runtime: "python3.11",
      Timeout: 300
    });
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "stock_analysis.handlers.worker.handler",
      Runtime: "python3.11",
      Timeout: 900
    });
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "stock_analysis.handlers.aggregator.handler",
      Runtime: "python3.11",
      Timeout: 300
    });
  });

  it("wires the worker Lambda to the SQS queue via event source mapping", () => {
    template.resourceCountIs("AWS::Lambda::EventSourceMapping", 1);
    template.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
      BatchSize: 1
    });
  });

  it("creates two nightly schedulers — coordinator at 5:00 PM and aggregator at 5:10 PM", () => {
    template.resourceCountIs("AWS::Scheduler::Schedule", 2);
    template.hasResourceProperties("AWS::Scheduler::Schedule", {
      ScheduleExpressionTimezone: "America/Los_Angeles",
      ScheduleExpression: "cron(0 17 ? * MON-FRI *)",
      Target: Match.objectLike({
        Arn: Match.objectLike({
          "Fn::GetAtt": Match.arrayWith([Match.stringLikeRegexp("^CoordinatorFunction")])
        })
      })
    });
    template.hasResourceProperties("AWS::Scheduler::Schedule", {
      ScheduleExpressionTimezone: "America/Los_Angeles",
      ScheduleExpression: "cron(10 17 ? * MON-FRI *)",
      Target: Match.objectLike({
        Arn: Match.objectLike({
          "Fn::GetAtt": Match.arrayWith([Match.stringLikeRegexp("^AggregatorFunction")])
        })
      })
    });
  });

  it("creates CloudWatch alarms for coordinator errors, aggregator errors, and DLQ depth", () => {
    template.resourceCountIs("AWS::CloudWatch::Alarm", 3);
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      AlarmName: "dev-coordinator-errors",
      Threshold: 1,
      TreatMissingData: "notBreaching",
    });
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      AlarmName: "dev-aggregator-errors",
      Threshold: 1,
      TreatMissingData: "notBreaching",
    });
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      AlarmName: "dev-worker-dlq-depth",
      Threshold: 1,
      TreatMissingData: "notBreaching",
    });
  });

  it("creates an SNS alarm topic", () => {
    template.resourceCountIs("AWS::SNS::Topic", 1);
    template.hasResourceProperties("AWS::SNS::Topic", {
      TopicName: "dev-stock-analysis-alarms",
    });
  });

  it("creates the SES placeholder identity", () => {
    template.resourceCountIs("AWS::SES::EmailIdentity", 1);
  });

  it("skips SES identity creation when no report email is configured", () => {
    const appWithoutEmail = new App();
    const stackWithoutEmail = new StockAnalysisInfraStack(appWithoutEmail, "NoEmailStack", {
      envName: "dev",
      reportEmailAddress: "",
      depsLayerArn: "arn:aws:lambda:us-west-2:123456789012:layer:dev-stock-analysis-deps:1",
    });
    const noEmailTemplate = Template.fromStack(stackWithoutEmail);

    noEmailTemplate.resourceCountIs("AWS::SES::EmailIdentity", 0);
  });

  it("creates the IAM roles for Lambda execution and nightly scheduling", () => {
    template.resourceCountIs("AWS::IAM::Role", 2);
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "lambda:InvokeFunction",
            Effect: "Allow"
          })
        ])
      }
    });
  });

  it("grants the Lambda role read access to external API keys in Secrets Manager", () => {
    // Resource is a Fn::Join intrinsic (account + region substitution), so match on action only.
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "secretsmanager:GetSecretValue",
            Effect: "Allow",
          })
        ])
      }
    });
  });

  it("passes the Gemini secret name to the aggregator Lambda environment", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "stock_analysis.handlers.aggregator.handler",
      Environment: {
        Variables: Match.objectLike({
          GEMINI_SECRET_NAME: "stock-analysis/gemini-api-key"
        })
      }
    });
  });

  it("passes the Earnings API secret name to the worker Lambda environment", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "stock_analysis.handlers.worker.handler",
      Environment: {
        Variables: Match.objectLike({
          EARNINGS_API_SECRET_NAME: "stock-analysis/earnings-api-key"
        })
      }
    });
  });
});
