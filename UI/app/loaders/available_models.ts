import { LoaderFunction } from "@remix-run/node";

export let loader: LoaderFunction = async () => {
    const dummy = {
        "Gemini": [{ id: "1", name: "Gemini 2.0 Flash" }],
        "Open AI": [{ id: "2", name: "GPT 4o" }],
        "Ollama": [{ id: "3", name: "Mistral AI" }],
    };
    try {
        const response = await fetch("http://localhost:5000/models/get-models");
        if (!response.ok) {
        return Response.json(dummy)
        }
        const data = await response.json();
        return Response.json(data);
    } catch (e) {
        return Response.json(dummy);
    }
};
