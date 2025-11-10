Frontend service (Next.js)

Build container:
- docker build -t chatbot-frontend ai-chatbot-framework/frontend/
- docker run -p 3000:3000 -e NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 chatbot-frontend

Or use docker-compose:
- docker compose -f ai-chatbot-framework/frontend/docker-compose.yml up --build

Static hosting (optional):
- Build: yarn build && yarn export (if using SSG) or copy .next/static and public to S3
- Provision CDN: terraform -chdir=infra/terraform/frontend init && terraform apply -var "bucket_name=your-bucket-name"
Runtime configuration:
- Client-side code must read API base from NEXT_PUBLIC_API_BASE_URL. Example:
  fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/health`)