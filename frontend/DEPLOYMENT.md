# Frontend Deployment Guide

## Overview

This is a Next.js 15 frontend microservice optimized for deployment on AWS ECS/Fargate or Vercel.

## Architecture

- **Build**: Multi-stage Docker build using Node.js 18-alpine
- **Output**: Standalone Next.js server for minimal image size
- **Runtime**: 512MB-1GB memory on ECS/Fargate with 2+ replicas
- **CDN**: CloudFront for caching and global distribution
- **Monitoring**: Sentry for error tracking and performance monitoring
- **Authentication**: NextAuth.js with Cognito/Auth0 support

## Environment Variables

### Required for Production

```bash
NEXT_PUBLIC_API_BASE_URL=https://api.example.com
NEXT_PUBLIC_AUTH_DOMAIN=https://auth.example.com
NEXT_PUBLIC_PUBLIC_URL=https://example.com
NEXTAUTH_URL=https://example.com
NEXTAUTH_SECRET=<secure-random-string>
```

### Optional

```bash
NEXT_PUBLIC_SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
NEXTAUTH_COGNITO_ID=<cognito-client-id>
NEXTAUTH_COGNITO_SECRET=<cognito-client-secret>
NEXTAUTH_COGNITO_ISSUER=https://cognito-idp.region.amazonaws.com/pool-id
NEXTAUTH_AUTH0_ID=<auth0-client-id>
NEXTAUTH_AUTH0_SECRET=<auth0-client-secret>
NEXTAUTH_AUTH0_ISSUER=https://your-tenant.auth0.com
```

## Local Development

```bash
npm install
npm run dev
```

Visit http://localhost:3000

## Docker Build

```bash
docker build -t frontend:latest .
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 \
  -e NEXT_PUBLIC_AUTH_DOMAIN=http://localhost:9000 \
  frontend:latest
```

## ECS/Fargate Deployment

### Task Definition

```json
{
  "family": "frontend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "containerDefinitions": [
    {
      "name": "frontend",
      "image": "your-ecr-repo/frontend:latest",
      "portMappings": [
        {
          "containerPort": 3000,
          "hostPort": 3000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "NODE_ENV",
          "value": "production"
        },
        {
          "name": "NEXT_PUBLIC_API_BASE_URL",
          "value": "https://api.example.com"
        }
      ],
      "secrets": [
        {
          "name": "NEXTAUTH_SECRET",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:nextauth-secret"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/frontend",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "wget --quiet --tries=1 --spider http://localhost:3000/ || exit 1"],
        "interval": 30,
        "timeout": 10,
        "retries": 3,
        "startPeriod": 40
      }
    }
  ]
}
```

### Service Configuration

- **Desired Count**: 2+ replicas
- **Load Balancer**: Application Load Balancer (ALB)
- **Target Group**: Port 3000
- **Health Check Path**: /
- **Auto Scaling**: CPU > 70% scale up, CPU < 30% scale down

## CloudFront CDN Setup

1. Create CloudFront distribution
2. Origin: ALB pointing to ECS service
3. Caching behavior:
   - Static assets (/_next/static/*): 1 year cache
   - Images (/images/*): 1 year cache
   - HTML pages: 1 hour cache
   - API routes: No cache (pass through)

## Monitoring

### Sentry Integration

1. Create Sentry project for Next.js
2. Set `NEXT_PUBLIC_SENTRY_DSN` environment variable
3. Errors and performance metrics automatically captured

### CloudWatch Logs

- Log Group: `/ecs/frontend`
- Retention: 30 days
- Metrics: CPU, Memory, Network

## Performance Optimization

- **Bundle Size**: Optimized with tree-shaking and code splitting
- **Image Optimization**: Next.js Image component with CDN caching
- **Static Generation**: SSG for admin pages where applicable
- **Caching Headers**: Aggressive caching for static assets

## Security

- Non-root user (nextjs) runs container
- Security headers configured (X-Frame-Options, X-Content-Type-Options, etc.)
- HTTPS enforced in production
- CORS configured for API calls
- JWT tokens for authentication

## Troubleshooting

### Container won't start
- Check environment variables are set
- Verify NEXTAUTH_SECRET is provided
- Check logs: `docker logs <container-id>`

### High memory usage
- Increase ECS task memory to 1GB
- Check for memory leaks in application code
- Monitor with CloudWatch

### Slow page loads
- Verify CloudFront is caching correctly
- Check API response times
- Review Next.js build output for large chunks

## Vercel Alternative

For simpler deployment without managing infrastructure:

```bash
vercel deploy --prod
```

Set environment variables in Vercel dashboard and redeploy.