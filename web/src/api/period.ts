// "What happened around <period>?" (docs/plans/tavily.md §3.6). A dated answer with a clear jump carries one
// action, made in code: the button's text, and the period behind it. A press goes back like a clarification's choice
// (`clarification_of` the message, `choice` the button's text); the server reads the period's dates and the
// measure from the action it saved on that message, never from the request.
import type { Message } from "@/api/types";

export interface PeriodAction {
  kind: "ask_period";
  label: string; // "What happened around March 2024?": the button's text, and what a press sends back
  period: string; // "March 2024" or "2020"
  start_date: string; // YYYY-MM-DD
  end_date: string;
  measure: string;
  result?: string;
}

/** The message's period buttons (the action kinds in `MessageAction` don't list this one). */
export function periodActions(message: Message): PeriodAction[] {
  return ((message.actions ?? []) as { kind: string }[]).filter((a): a is PeriodAction => a.kind === "ask_period");
}
