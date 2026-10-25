// Story cards (TRD §4.6): the list, edits, suggestions, badges, refresh and evidence.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./client";
import type { Card, CardBody, Evidence } from "./types";

export const cardsKey = (datasetId: string) => ["cards", datasetId] as const;

export function useCards(datasetId: string | undefined) {
  return useQuery({
    queryKey: cardsKey(datasetId ?? ""),
    enabled: !!datasetId,
    queryFn: () => request<Card[]>("GET", `/api/v1/datasets/${datasetId}/cards`),
  });
}

export function useEvidence(cardId: string | null, chipId: string | null) {
  return useQuery({
    queryKey: ["evidence", cardId, chipId],
    enabled: !!cardId && !!chipId,
    queryFn: () => request<Evidence>("GET", `/api/v1/cards/${cardId}/evidence/${chipId}`),
  });
}

export function useCardActions(datasetId: string) {
  const qc = useQueryClient();
  const put = (card: Card) =>
    qc.setQueryData<Card[]>(cardsKey(datasetId), (list) => list?.map((c) => (c.id === card.id ? card : c)));
  const post = (path: string) => (id: string) => request<Card>("POST", `/api/v1/cards/${id}/${path}`);
  return {
    edit: useMutation({
      mutationFn: ({ id, headline, body }: { id: string; headline?: CardBody; body?: CardBody }) =>
        request<Card>("PATCH", `/api/v1/cards/${id}`, { headline, body }),
      onSuccess: put,
    }),
    accept: useMutation({ mutationFn: post("accept-suggestion"), onSuccess: put }),
    dismiss: useMutation({ mutationFn: post("dismiss-suggestion"), onSuccess: put }),
    dismissBadge: useMutation({ mutationFn: post("dismiss-badge"), onSuccess: put }),
    refresh: useMutation({
      mutationFn: (id: string) => request("POST", `/api/v1/cards/${id}/refresh`),
      onSuccess: () => qc.invalidateQueries({ queryKey: cardsKey(datasetId) }),
    }),
    remove: useMutation({
      mutationFn: (id: string) => request("DELETE", `/api/v1/cards/${id}`),
      onSuccess: () => qc.invalidateQueries({ queryKey: cardsKey(datasetId) }),
    }),
    restore: useMutation({
      mutationFn: (id: string) => request<Card>("POST", `/api/v1/cards/${id}/restore`),
      onSuccess: () => qc.invalidateQueries({ queryKey: cardsKey(datasetId) }),
    }),
  };
}

/** A card's text as plain words (chips as their values), e.g. for "Ask why". */
export function plainText(body: CardBody, facts: Card["facts"] = {}): string {
  return body.blocks
    .map((b) => b.runs.map((r) => (r.type === "chip" ? (r.key && facts[r.key]?.formatted) || r.value : r.type === "label" ? r.text ?? "" : r.text)).join(""))
    .join(" ")
    .trim();
}
