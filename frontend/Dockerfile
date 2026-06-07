FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Set NEXT_PUBLIC_BACKEND_API to point to the server API URL during build time
# If not set, it will default to http://127.0.0.1:8000 at runtime
ARG NEXT_PUBLIC_BACKEND_API
ENV NEXT_PUBLIC_BACKEND_API=${NEXT_PUBLIC_BACKEND_API}

RUN npm run build

EXPOSE 3000

ENV PORT 3000
ENV HOSTNAME "0.0.0.0"

CMD ["npm", "start"]
