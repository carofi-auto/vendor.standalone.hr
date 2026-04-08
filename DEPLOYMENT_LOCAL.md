aws ecr get-login-password --region us-east-1 --profile carofi \
| docker login --username AWS \
--password-stdin 319286726886.dkr.ecr.us-east-1.amazonaws.com


docker buildx build \
  --no-cache \
  --platform linux/amd64 \
  -t 319286726886.dkr.ecr.us-east-1.amazonaws.com/prod/vendor.standalone.hr:latest \
  --push .