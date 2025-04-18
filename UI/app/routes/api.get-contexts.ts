import type { LoaderFunction } from "@remix-run/node";

// Backend API URL
const FLASK_API_URL = "http://127.0.0.1:8000/generate/get-contexts";

export const loader: LoaderFunction = async () => {
    try {
        // Fetch contexts from the backend Flask API
        const response = await fetch(FLASK_API_URL, {
            method: "GET",
            headers: {
                "Content-Type": "application/json",
            },
        });

        // Handle errors
        if (!response.ok) {
            const errorData = await response.json();
            return Response.json(
                { error: errorData.error || "Failed to fetch contexts" },
                { status: response.status }
            );
        }

        // Return the contexts data
        const data = await response.json();
        return Response.json(data);
    } catch (error) {
        console.error("Error fetching contexts:", error);
        return Response.json(
            { error: "Internal server error: " + String(error) },
            { status: 500 }
        );
    }
};