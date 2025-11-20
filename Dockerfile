FROM python:3.11-slim

# Install Node.js and npm
RUN apt-get update && apt-get install -y nodejs npm git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
COPY dashboard/api/requirements.txt ./dashboard/api/
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r dashboard/api/requirements.txt
RUN pip install gunicorn

# Copy the rest of the application
COPY . .

# Build the React frontend
WORKDIR /app/dashboard
RUN npm install
RUN npm run build

# Go back to root
WORKDIR /app

# Expose the port Flask runs on
ENV PORT=5000
EXPOSE $PORT

# Create a start script
COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
