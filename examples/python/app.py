import os
import requests
import json
import logging

logger = logging.getLogger(__name__)

# Get API base URL from environment variable with default for local development
API_BASE_URL = os.getenv("CHATBOT_API_URL", "http://localhost:8001")

""" 
define initial payload
set input = 'init_conversation' so that bot will return default welcome message
"""
payload = {
    "currentNode": "",
    "complete": None,
    "context": {},
    "parameters": [],
    "extractedParameters": {},
    "speechResponse": "",
    "intent": {},
    "input": "init_conversation",
    "missingParameters": [],
}

while True:
    try:
        r = requests.post(f"{API_BASE_URL}/api/v1", json=payload, timeout=10)
        r.raise_for_status()
        
        # replace payload variable with api result
        payload = json.loads(r.text)
        
        logger.info("Iky\t" + payload.get("speechResponse"))
        
        # read user input
        payload["input"] = input("You:\t")
        
    except requests.exceptions.Timeout:
        logger.error("Request timeout: API server did not respond within 10 seconds")
        logger.info("Please ensure the API server is running at: %s", API_BASE_URL)
        break
    except requests.exceptions.ConnectionError:
        logger.error("Connection error: Unable to reach API server at %s", API_BASE_URL)
        logger.info("Please ensure the API server is running and accessible")
        break
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP error occurred: %s", e)
        break
    except json.JSONDecodeError as e:
        logger.error("Failed to parse API response as JSON: %s", e)
        break
    except requests.exceptions.RequestException as e:
        logger.error("Request failed: %s", e)
        break
    except KeyboardInterrupt:
        logger.info("Conversation ended by user")
        break
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        break