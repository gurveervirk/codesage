import type { ActionFunction, LoaderFunction } from "@remix-run/node";

const FLASK_API_URL = "http://127.0.0.1:5000/generate/generate-example";

let storedPrompt: string | null = null;

export const action: ActionFunction = async ({ request }) => {
  const requestBody = await request.json();
  const prompt = requestBody.prompt;
  console.log("Received prompt:", requestBody);
  if (typeof prompt !== "string") {
    return Response.json({ error: "Invalid input" }, { status: 400 });
  }

  storedPrompt = prompt;

  return Response.json({ status: "ok" });
};

export const loader: LoaderFunction = async () => {
  if (storedPrompt === null) {
    return new Response("data: Error: Missing Prompt\n\n", {
      headers: { "Content-Type": "text/event-stream" },
      status: 400,
    });
  }

  const promptToUse = storedPrompt;
  storedPrompt = null;

  try {
    const flaskResponse = await fetch(FLASK_API_URL, {
      method: "POST",
      body: JSON.stringify({ prompt: promptToUse }),
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!flaskResponse.ok) {
      throw new Error(
        `Failed to fetch from Flask API: ${flaskResponse.status} ${flaskResponse.statusText}`
      );
    }

    return new Response(flaskResponse.body, {
      headers: {
        "Content-Type": "text/event-stream",
      },
    });

  } catch (error: any) {
    console.error("Error fetching from Flask API:", error);
    return new Response(`data: Error: ${error.message}\n\n`, {
      headers: { "Content-Type": "text/event-stream" },
      status: 500,
    });
  }
};