import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { IdentityClient } from "../identity/client";
import type { createNotificationClient } from "./client";

export type NotificationClient = ReturnType<typeof createNotificationClient>;
export type NotificationSession = Pick<
  Awaited<ReturnType<IdentityClient["currentSession"]>>,
  "account_id" | "role" | "suspended"
>;

export const notificationKeys = {
  all: ["notifications"] as const,
  inbox: (accountId: string, first = 20, after?: string | null) =>
    ["notifications", accountId, "inbox", first, after] as const,
};

export function useNotificationInbox(
  client: NotificationClient,
  session: NotificationSession | null,
  first = 20,
  after?: string | null,
) {
  const queryClient = useQueryClient();
  const eligible =
    session?.role === "member" && session.suspended === false;
  const accountId = eligible ? session.account_id : "";
  const inbox = useQuery({
    queryKey: notificationKeys.inbox(accountId, first, after),
    queryFn: () => client.fetchInbox({ first, after }),
    enabled: eligible,
    staleTime: 0,
  });
  const mark = useMutation({
    mutationFn: (notificationId: string) => client.markRead(notificationId),
    onSettled: () => {
      if (accountId)
        void queryClient.invalidateQueries({
          queryKey: notificationKeys.inbox(accountId),
        });
    },
  });

  useEffect(() => {
    if (!eligible || !accountId) return;
    const invalidate = () =>
      void queryClient.invalidateQueries({
        queryKey: notificationKeys.inbox(accountId),
      });
    const unsubscribe = client.subscribeToChanges(invalidate);
    return () => {
      unsubscribe();
      queryClient.removeQueries({
        queryKey: ["notifications", accountId],
      });
    };
  }, [accountId, client, eligible, queryClient]);

  return {
    inbox,
    markRead: mark.mutateAsync,
    isMarkingRead: mark.isPending,
    markError: mark.error,
  };
}
