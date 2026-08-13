# syntax=docker/dockerfile:1
FROM node:22-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
RUN npm install --global npm@11.6.2

FROM base AS dependencies
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci

FROM dependencies AS development
COPY apps/frontend/ ./
CMD ["npm", "run", "dev"]

FROM dependencies AS builder
ARG APP_ENV=production
ARG NEXT_PUBLIC_DEMO_MODE=false
ENV APP_ENV=$APP_ENV \
    NEXT_PUBLIC_DEMO_MODE=$NEXT_PUBLIC_DEMO_MODE
COPY apps/frontend/ ./
RUN npm run build

FROM node:22-alpine AS production
ARG NEXT_PUBLIC_DEMO_MODE=false
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_DEMO_MODE=$NEXT_PUBLIC_DEMO_MODE \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["node", "-e", "const p=process.env.NEXT_PUBLIC_DEMO_MODE==='true'?'/':'/api/health/live';fetch('http://127.0.0.1:3000'+p).then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
