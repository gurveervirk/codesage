import type { ActionFunction } from "@remix-run/node";

// Backend API URL
const FLASK_API_URL = "http://127.0.0.1:8000/generate/load-context";

export const action: ActionFunction = async ({ request }) => {
    try {
        // Get the request body
        const requestBody = await request.json();
        const contextId = requestBody.id;

        if (typeof contextId !== "string") {
            return Response.json({ error: "Invalid input: context id must be a string" }, { status: 400 });
        }

        // Send load context request to the backend Flask API
        const response = await fetch(FLASK_API_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ id: contextId }),
        });

        // Handle errors
        if (!response.ok) {
            const errorData = await response.json();
            return Response.json(
                { error: errorData.error || "Failed to load context" },
                { status: response.status }
            );
        }

        // Return the chat history from the loaded context
        const data = await response.json();
        return Response.json(data);
    } catch (error) {
        console.error("Error loading context:", error);
        return Response.json(
            { error: "Internal server error: " + String(error) },
            { status: 500 }
        );
    }
};