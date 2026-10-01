import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ProductClient, ProductSave, ProductState } from "./client";

export type ProductDraftValues = Omit<ProductSave, "version">;
export type ProductAutosaveStatus =
  | "saved"
  | "dirty"
  | "saving"
  | "not-saved"
  | "conflict";
type SubmissionReadiness = {
  waitForUploads: () => Promise<unknown>;
  saveLatest: () => Promise<{ version: number }>;
};

export const productKeys = {
  viewer: ["products", "viewer"] as const,
  detail: (id: string) => ["products", "viewer", id] as const,
  reviewQueue: ["products", "review-queue"] as const,
  review: (id: string) => ["products", "review", id] as const,
  topics: ["products", "topics"] as const,
};

export function useViewerProducts(client: ProductClient) {
  return useQuery({
    queryKey: productKeys.viewer,
    queryFn: () => client.fetchViewerProducts(),
  });
}

export function useViewerProduct(client: ProductClient, productId: string) {
  return useQuery({
    queryKey: productKeys.detail(productId),
    queryFn: () => client.fetchViewerProduct({ id: productId }),
    enabled: productId.length > 0,
  });
}

export function useReviewQueue(
  client: ProductClient,
  first = 20,
  after?: string | null,
) {
  return useQuery({
    queryKey: [...productKeys.reviewQueue, first, after],
    queryFn: () => client.fetchReviewQueue({ first, after }),
  });
}

export function useReviewProduct(client: ProductClient, productId: string) {
  return useQuery({
    queryKey: productKeys.review(productId),
    queryFn: () => client.fetchReviewProduct({ id: productId }),
    enabled: productId.length > 0,
  });
}

export function useTopicChoices(client: ProductClient) {
  return useQuery({
    queryKey: productKeys.topics,
    queryFn: client.fetchTopicChoices,
  });
}

export function useCreateDraft(client: ProductClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.createDraft,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: productKeys.viewer });
    },
  });
}

export function useProductAutosave(
  client: ProductClient,
  productId: string,
  initial: ProductDraftValues & { version: number },
  debounceMs = 400,
) {
  const [values, setValues] = useState<ProductDraftValues>(() =>
    withoutVersion(initial),
  );
  const [status, setStatus] = useState<ProductAutosaveStatus>("saved");
  const valuesRef = useRef(values);
  const savedRef = useRef<ProductDraftValues>(withoutVersion(initial));
  const versionRef = useRef(initial.version);
  const statusRef = useRef<ProductAutosaveStatus>("saved");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef<Promise<ProductState> | null>(null);
  const mountedRef = useRef(true);

  const updateStatus = useCallback((next: ProductAutosaveStatus) => {
    statusRef.current = next;
    if (mountedRef.current) setStatus(next);
  }, []);

  const saveLatest = useCallback(async (): Promise<ProductState> => {
    if (statusRef.current === "conflict")
      throw new Error("Resolve this version conflict before saving again.");
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (inFlightRef.current !== null) {
      await inFlightRef.current;
      if (!sameValues(valuesRef.current, savedRef.current)) return saveLatest();
      return { id: productId, version: versionRef.current, status: "draft" };
    }
    if (sameValues(valuesRef.current, savedRef.current)) {
      updateStatus("saved");
      return { id: productId, version: versionRef.current, status: "draft" };
    }

    const snapshot = valuesRef.current;
    updateStatus("saving");
    const request = client.saveProduct(productId, {
      ...snapshot,
      version: versionRef.current,
    });
    inFlightRef.current = request;
    let result: ProductState;
    try {
      result = await request;
      savedRef.current = snapshot;
      versionRef.current = result.version;
    } catch (error) {
      const statusCode =
        typeof error === "object" && error !== null && "status" in error
          ? error.status
          : undefined;
      updateStatus(statusCode === 409 ? "conflict" : "not-saved");
      throw error;
    } finally {
      inFlightRef.current = null;
    }
    if (sameValues(valuesRef.current, savedRef.current)) updateStatus("saved");
    else {
      updateStatus("dirty");
      return saveLatest();
    }
    return result;
  }, [client, productId, updateStatus]);

  const schedule = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      void saveLatest().catch(() => undefined);
    }, debounceMs);
  }, [debounceMs, saveLatest]);

  const edit = useCallback(
    (patch: Partial<ProductDraftValues>) => {
      valuesRef.current = { ...valuesRef.current, ...patch };
      setValues(valuesRef.current);
      if (statusRef.current !== "conflict") {
        updateStatus("dirty");
        schedule();
      }
    },
    [schedule, updateStatus],
  );

  const retry = useCallback(async () => {
    if (statusRef.current === "conflict") return;
    await saveLatest();
  }, [saveLatest]);

  useEffect(() => {
    mountedRef.current = true;
    const reconnect = () => {
      if (statusRef.current === "not-saved" && navigator.onLine !== false)
        void retry().catch(() => undefined);
    };
    window.addEventListener("online", reconnect);
    return () => {
      mountedRef.current = false;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      window.removeEventListener("online", reconnect);
    };
  }, [retry]);

  return {
    values,
    status,
    edit,
    retry,
    saveLatest,
    version: versionRef.current,
  };
}

export function useSubmitProduct(client: ProductClient) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      productId,
      readiness,
    }: {
      productId: string;
      readiness: SubmissionReadiness;
    }) => client.submitWhenReady(productId, readiness),
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({ queryKey: productKeys.viewer });
      void queryClient.invalidateQueries({
        queryKey: productKeys.detail(variables.productId),
      });
    },
  });
}

function withoutVersion(
  value: ProductDraftValues & { version: number },
): ProductDraftValues {
  const { version, ...fields } = value;
  void version;
  return fields;
}

function sameValues(
  left: ProductDraftValues,
  right: ProductDraftValues,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
