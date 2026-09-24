FROM node:22-alpine

WORKDIR /app

# Copia arquivos de configuração
COPY package.json package-lock.json ./
COPY next.config.js ./
COPY tsconfig.json ./
COPY tailwind.config.ts ./
COPY postcss.config.js ./

# Instala dependências (--legacy-peer-deps evita ERESOLVE que quebrava o build)
RUN npm install --legacy-peer-deps

# Copia o código
COPY app ./app
COPY components ./components
COPY lib ./lib
COPY public ./public
COPY middleware.ts ./middleware.ts

# Build
RUN npm run build

EXPOSE 3000

# Railway injeta a porta via $PORT
CMD ["sh", "-c", "npm start -- -p ${PORT:-3000}"]