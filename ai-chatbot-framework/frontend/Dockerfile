# Multi-stage build for Next.js production (standalone)
FROM node:18-alpine AS deps
WORKDIR /usr/src/app

# Install dependencies (use yarn if lockfile present)
COPY package.json yarn.lock* package-lock.json* pnpm-lock.yaml* ./
RUN if [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
    elif [ -f package-lock.json ]; then npm ci; \
    elif [ -f pnpm-lock.yaml ]; then npm i -g pnpm && pnpm i --frozen-lockfile; \
    else yarn install --frozen-lockfile; fi

FROM node:18-alpine AS builder
WORKDIR /usr/src/app
COPY --from=deps /usr/src/app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# Build the app in standalone mode (configured in next.config.ts)
RUN npm run build || yarn build

FROM node:18-alpine AS runner
WORKDIR /usr/src/app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Copy standalone output
COPY --from=builder /usr/src/app/.next/standalone ./
COPY --from=builder /usr/src/app/.next/static ./.next/static
COPY --from=builder /usr/src/app/public ./public

# Expose Next.js default port
EXPOSE 3000

# Runtime envs are read from process.env (NEXT_PUBLIC_*)
CMD ["node", "server.js"]