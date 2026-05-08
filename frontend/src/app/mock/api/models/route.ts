export function GET() {
  return Response.json({
    models: [
      {
        id: "deepseek-v3.2",
        name: "deepseek-v3.2",
        model: "deepseek-chat",
        display_name: "DeepSeek v3.2",
        supports_thinking: true,
      },
      {
        id: "gpt-5",
        name: "gpt-5",
        model: "gpt-5",
        display_name: "GPT-5",
        supports_thinking: true,
      },
      {
        id: "gemini-3-pro",
        name: "gemini-3-pro",
        model: "gemini-3-pro",
        display_name: "Gemini 3 Pro",
        supports_thinking: true,
      },
    ],
  });
}
