import { type ActionFunctionArgs } from "@remix-run/node";

export const action = async ({ request }:ActionFunctionArgs) => {
  try {
    const message = await request.json();
    const response = await fetch("http://localhost:5000/upload-module", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message ),
    });

    const data = await response.json();
    console.log(data);
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: "Internal Server Error" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};
