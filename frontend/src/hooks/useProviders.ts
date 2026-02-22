import { useEffect, useState } from "react";
import type { Provider, ProviderModel, Agent } from "../types";
import * as api from "../api";

export function useProviders() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [providerId, setProviderId] = useState("");
  const [modelId, setModelId] = useState("");
  const [agent, setAgent] = useState("build");

  const modelRef = providerId && modelId ? `${providerId}/${modelId}` : "";

  function currentModels(): ProviderModel[] {
    return providers.find((item) => item.id === providerId)?.models ?? [];
  }

  function selectProvider(id: string) {
    setProviderId(id);
    setModelId(providers.find((item) => item.id === id)?.models[0]?.id ?? "");
  }

  async function loadProviders(): Promise<void> {
    const base = await api.providers.list();
    const result = await Promise.all(
      base.map(async (item) => {
        const id = String(item.id ?? "");
        if (!id) return null;
        const models = await api.providers.models(id);
        return {
          id,
          name: String(item.name ?? id),
          models: models.map((m) => ({ id: String(m.id), name: String(m.name ?? m.id) })),
        } as Provider;
      }),
    );
    const clean = result.filter((item): item is Provider => item !== null);
    setProviders(clean);
    if (clean.length === 0) return;
    setProviderId((curr) => curr || clean[0]!.id);
    const first = clean[0]!.models[0];
    if (first) setModelId((curr) => curr || first.id);
  }

  async function loadAgents(): Promise<void> {
    const list = await api.agents.list();
    setAgents(list);
    if (list.length === 0) return;
    setAgent((curr) => curr || list[0].name);
  }

  useEffect(() => {
    void Promise.all([loadProviders(), loadAgents()]);
  }, []);

  return {
    providers,
    agents,
    providerId,
    modelId,
    modelRef,
    agent,
    setAgent,
    setModelId,
    selectProvider,
    currentModels,
  };
}
