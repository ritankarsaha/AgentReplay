export const INIT_SNIPPET = `import agentreplay

agentreplay.init()  # reads AGENTREPLAY_API_KEY

# ...build and run your agent as usual -- Anthropic and OpenAI
# calls are recorded automatically.
agentreplay.shutdown()  # flush before the process exits`;
