# LeadGen API

B2B Lead Generation backend system for scraping LinkedIn profiles, enriching with verified emails, and generating AI-powered cold email sequences.

## Quick Start

```bash
# Clone and setup
cd leadgen-api
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start services
docker-compose up -d

# Run migrations
alembic upgrade head

# Start API
uvicorn leadgen.main:app --reload
```

## Configuration

Copy `.env.example` to `.env` and fill in your API keys:

- `RAPIDAPI_KEY` - LinkedIn scraping (required)
- `EMAIL_VERIFICATION_API_URL` - Your email verification endpoint
- `OPENAI_API_KEY` - For AI features (optional)

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
