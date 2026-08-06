FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install --legacy-peer-deps

COPY . .

ARG BUILD_CONFIG=production
RUN node_modules/.bin/ng build --configuration ${BUILD_CONFIG} && \
    node_modules/.bin/ng run frontend:server:${BUILD_CONFIG}

FROM node:20-alpine

WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package*.json ./
RUN npm install --legacy-peer-deps --omit=dev

EXPOSE 4000

CMD ["node", "dist/frontend/server/main.js"]
