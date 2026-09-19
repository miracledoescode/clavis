// Co-Pilot — the approve/reject UI and RLHF capture surface. Talks to the
// engine's /v1/copilot/proposals|decisions and approve/reject endpoints,
// which route through the same AgentLoop path the Telegram webhook uses.
export { CoPilot } from "./co-pilot";
