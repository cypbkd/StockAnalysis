#!/usr/bin/env node
import { App } from "aws-cdk-lib";
import { StockAnalysisInfraStack } from "../lib/stock-analysis-infra-stack";

const app = new App();

new StockAnalysisInfraStack(app, "StockAnalysisInfraDev", {
  envName: "dev",
  reportEmailAddress: process.env.REPORT_EMAIL_ADDRESS,
  // Layer published once via: aws lambda publish-layer-version --layer-name dev-stock-analysis-deps ...
  // Update this ARN whenever deps change and a new layer version is published.
  depsLayerArn: "arn:aws:lambda:us-west-2:841425310647:layer:dev-stock-analysis-deps:3",
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION
  }
});
