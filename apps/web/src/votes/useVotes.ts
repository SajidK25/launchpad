import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { IdentityClient } from "../identity/client";
import { createVoteClient } from "./client";

export function useVoteCommand(
  identityClient: IdentityClient,
  productId: string,
  launchDate: string,
) {
  const queryClient = useQueryClient();
  const client = useMemo(
    () => createVoteClient(undefined, identityClient),
    [identityClient],
  );
  return useMutation({
    mutationFn: ({
      active,
      idempotencyKey,
      turnstileToken,
    }: {
      active: boolean;
      idempotencyKey: string;
      turnstileToken?: string;
    }) =>
      active
        ? client.cast(productId, idempotencyKey, turnstileToken)
        : client.withdraw(productId, idempotencyKey, turnstileToken),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["launches", "daily-ranking", launchDate],
      });
      void queryClient.invalidateQueries({
        queryKey: ["launches", "daily-ranking", "today"],
      });
    },
  });
}
