import { type ActionFunctionArgs } from "@remix-run/node";

export const action = async ({ request }: ActionFunctionArgs) => {
  try {
   
    const formData = await request.json();
    
    const moduleName = formData?.module_name;
    if (!moduleName || typeof moduleName !== 'string') {
      return new Response(JSON.stringify({ error: "Module name is required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const response = await fetch("http://localhost:5000/upload-module", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module_name: moduleName }),
    });

    const data = await response.json();
    console.log(data);
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "An unknown error occurred";
    return new Response(JSON.stringify({ error: errorMessage }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};
