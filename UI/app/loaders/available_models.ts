import { data } from "@remix-run/node";

export const loader = async () => {
    const dummy = {
        "Gemini": [{ id: "1", name: "Gemini 2.0 Flash" }],
        "Open AI": [{ id: "2", name: "GPT 4o" }],
        "Ollama": [{ id: "3", name: "Mistral AI" }],
    };
    try {
        const response = await fetch("http://127.0.0.1:8000/models/get-models");
        if (!response.ok) {
            return data(dummy)
        }
        const json = await response.json();
        return data(json);
    } catch (e) {
        return data(dummy);
    }
};
