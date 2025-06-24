import type { ActionFunction } from "@remix-run/node";

// Backend API URL
const FLASK_API_URL = "http://127.0.0.1:8000/generate/chat-workflow";

export const action: ActionFunction = async ({ request }) => {
    try {
        // Get the request body
        const requestBody = await request.json();
        const prompt = requestBody.prompt;

        if (typeof prompt !== "string") {
            return Response.json({ error: "Invalid input: prompt must be a string" }, { status: 400 });
        }

        // Forward the request to the backend Flask API
        const flaskResponse = await fetch(FLASK_API_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ prompt }),
        });

        // Handle the response
        if (!flaskResponse.ok) {
            const errorData = await flaskResponse.json();
            return Response.json(
                { error: errorData.error || "Failed to process request" },
                { status: flaskResponse.status }
            );
        }

        // Return the response from the Flask API
        const responseData = await flaskResponse.json();
        return Response.json(responseData);
    } catch (error) {
        console.error("Error in chat-workflow API route:", error);
        return Response.json(
            { error: "Internal server error: " + String(error) },
            { status: 500 }
        );
    }
};