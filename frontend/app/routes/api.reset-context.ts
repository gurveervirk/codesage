import type { ActionFunction } from "@remix-run/node";

// Backend API URL
const FLASK_API_URL = "http://127.0.0.1:8000/generate/reset-context";

export const action: ActionFunction = async () => {
    try {
        // Send reset request to the backend Flask API
        const response = await fetch(FLASK_API_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            }
        });

        // Handle errors
        if (!response.ok) {
            const errorData = await response.json();
            return Response.json(
                { error: errorData.error || "Failed to reset context" },
                { status: response.status }
            );
        }

        // Return success response
        const data = await response.json();
        return Response.json(data);
    } catch (error) {
        console.error("Error resetting context:", error);
        return Response.json(
            { error: "Internal server error: " + String(error) },
            { status: 500 }
        );
    }
};