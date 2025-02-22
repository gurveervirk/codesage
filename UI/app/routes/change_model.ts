import { type ActionFunctionArgs } from "@remix-run/node";
export const action = async ({ request }:ActionFunctionArgs) => {
  try {
    const formData = await request.formData();
    const id = formData.get("modelId");
    const provider = formData.get("provider");
    if (typeof id !== "string" || typeof provider !== "string") {
      return { success: false };
    }
    const response = await fetch("http://localhost:5000/models/change-model", {
      method: "POST",
      body: JSON.stringify({ id, provider }),
      headers: {
        "Content-Type": "application/json",
      },
    });
    console.log(response);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return { success: true };
  } catch (error) {
    console.error("Failed to change model:", error);
    return { success: false, error: (error as Error).message }; 
  }
}