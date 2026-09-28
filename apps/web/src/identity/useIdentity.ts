import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { IdentityRequestError, type IdentityClient } from "./client";

export const identityKeys = {
  session: ["identity", "session"] as const,
};

export function useCurrentSession(client: IdentityClient) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: identityKeys.session,
    queryFn: async () => {
      try {
        return await client.currentSession();
      } catch (error) {
        if (error instanceof IdentityRequestError && error.status === 401) {
          queryClient.removeQueries({ queryKey: identityKeys.session });
          queryClient.removeQueries({ queryKey: ["profiles"] });
        }
        throw error;
      }
    },
    staleTime: 30_000,
  });
}

export function useLogin(client: IdentityClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.login,
    onSuccess: (session) => {
      queryClient.removeQueries({ queryKey: ["profiles"] });
      queryClient.setQueryData(identityKeys.session, session);
    },
  });
}

export function useLogout(client: IdentityClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.logout,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: identityKeys.session });
      queryClient.removeQueries({ queryKey: ["profiles"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: identityKeys.session });
    },
  });
}

export function useVerify(client: IdentityClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.verify,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: identityKeys.session });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: identityKeys.session });
    },
  });
}

export function useResetPassword(client: IdentityClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.resetPassword,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: identityKeys.session });
      queryClient.removeQueries({ queryKey: ["profiles"] });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: identityKeys.session });
    },
  });
}

export function useRegister(client: IdentityClient) {
  return useMutation({ mutationFn: client.register });
}

export function useRequestVerification(client: IdentityClient) {
  return useMutation({ mutationFn: client.requestVerification });
}

export function useRequestPasswordReset(client: IdentityClient) {
  return useMutation({ mutationFn: client.requestPasswordReset });
}
