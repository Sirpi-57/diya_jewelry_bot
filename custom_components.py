from typing import Any, Dict, Text
from rasa.core.nlg.contextual_response_rephraser import ContextualResponseRephraser
from rasa_sdk.interfaces import Tracker as DialogueStateTracker

class CustomResponseRephraser(ContextualResponseRephraser):
    async def rephrase(self, response: Dict[Text, Any], tracker: DialogueStateTracker) -> Dict[Text, Any]:
        # Check if this is a response from the jewelry PDF chatbot
        metadata = response.get("metadata", {})
        
        # Don't rephrase if it's from the jewelry chatbot or explicitly marked to not rephrase
        if metadata.get("from_jewelry_pdf") or metadata.get("rephrase") is False:
            return response
        else:
            # Use normal rephrasing for other responses
            return await super().rephrase(response, tracker)