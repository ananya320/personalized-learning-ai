from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Get the Mongo URI
MONGO_URI = os.getenv("MONGO_URI")

# Debug print — helps check if it loaded
if not MONGO_URI:
    raise ValueError("❌ MONGO_URI is not set. Check your .env file and path!")

print("✅ Mongo URI loaded successfully")

# Connect to MongoDB
client = AsyncIOMotorClient(MONGO_URI)
db = client.get_default_database()  # or client["my_database_name"]

