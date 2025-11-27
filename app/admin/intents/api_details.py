"""API details schema for intent API triggers."""
from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import List, Dict


class ApiDetails(BaseModel):
    """API details schema for intent API triggers with URL validation."""

    url: str = Field(..., description="API endpoint URL")
    requestType: str = Field(..., description="HTTP request method (GET, POST, PUT, DELETE, etc.)")
    headers: List[Dict[str, str]] = Field(default_factory=list, description="Request headers")
    isJson: bool = Field(default=False, description="Whether request body is JSON")
    jsonData: str = Field(default="{}", description="JSON request body")

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        """Validate that URL is a valid HTTP/HTTPS URL.

        Args:
            v: URL string to validate

        Returns:
            Validated URL string

        Raises:
            ValueError: If URL is not a valid HTTP/HTTPS URL
        """
        if not v:
            raise ValueError("URL cannot be empty")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("requestType")
    @classmethod
    def validate_request_type(cls, v: str) -> str:
        """Validate that request type is a valid HTTP method.

        Args:
            v: Request type string to validate

        Returns:
            Validated request type string

        Raises:
            ValueError: If request type is not a valid HTTP method
        """
        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        if v.upper() not in valid_methods:
            raise ValueError(f"Request type must be one of {valid_methods}")
        return v.upper()

    @field_validator("jsonData")
    @classmethod
    def validate_json_data(cls, v: str) -> str:
        """Validate that jsonData is valid JSON string.

        Args:
            v: JSON string to validate

        Returns:
            Validated JSON string

        Raises:
            ValueError: If jsonData is not valid JSON
        """
        import json
        try:
            json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(f"jsonData must be valid JSON: {e}")
        return v

    def get_headers(self) -> Dict[str, str]:
        """Convert headers list to dictionary format.

        Returns:
            Dictionary mapping header keys to values
        """
        headers = {}
        for header in self.headers:
            if "headerKey" in header and "headerValue" in header:
                headers[header["headerKey"]] = header["headerValue"]
        return headers