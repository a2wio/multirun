# The dashboard: node, no build step — the browser gets tailwind and
# htmx off the CDN, the image ships exactly what's in dashboard/.
FROM node:26-alpine

WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

COPY dashboard/ ./

ENV NODE_ENV=production
USER node
EXPOSE 3000
CMD ["node", "server.js"]
