FROM node:20-alpine

WORKDIR /app

# Copia arquivos de configuração
COPY package.json ./
COPY next.config.js ./
COPY tsconfig.json ./
COPY tailwind.config.ts ./
COPY postcss.config.js ./

# Instala dependências
RUN npm install

# Copia o código
COPY app ./app
COPY components ./components
COPY lib ./lib
COPY middleware.ts ./middleware.ts

# Build
RUN npm run build

EXPOSE 3000

CMD ["sh", "-c", "npm start -- -p ${PORT:-3000}"]