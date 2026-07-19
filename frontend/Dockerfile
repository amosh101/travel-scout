FROM node:22-alpine

WORKDIR /app

# Install deps (cached layer for package.json changes only)
COPY package*.json ./
RUN npm ci

# Source is mounted via docker-compose volume in dev mode
# (`./frontend:/app` and `frontend_node_modules:/app/node_modules`)
# so the dev server has hot-reload.
COPY . .

EXPOSE 3000

# Default command; docker-compose overrides this to `npm run dev`
# for the local-dev path. Build-step is skipped (use `npm run build`
# in the host if you want a production image).
CMD ["npm", "run", "dev"]
