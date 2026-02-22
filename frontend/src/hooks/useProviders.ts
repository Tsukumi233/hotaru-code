import { useEffect, useState } from "react";
import type { Provider, ProviderModel, Agent } from "../types";
import * as api from "../api";

function hasModel(providers: Provider[], providerId: string, modelId: string): boolean {
  return providers.some((provider) => provider.id === providerId && provider.models.some((model) => model.id === modelId));
}

function firstModel(providers: Provider[]): { providerId: string; modelId: string } {
  for (const provider of providers) {
    const model = provider.models[0];
    if (model) return { providerId: provider.id, modelId: model.id };
  }
  return { providerId: providers[0]?.id ?? "", modelId: "" };
}

export function useProviders() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [providerId, setProviderId] = useState("");
  const [modelId, setModelId] = useState("");
  const [agent, setAgent] = useState("");
  const [ready, setReady] = useState(false);

  const modelRef = providerId && modelId ? `${providerId}/${modelId}` : "";

  function currentModels(): ProviderModel[] {
    return providers.find((item) => item.id === providerId)?.models ?? [];
  }

  function selectProvider(id: string) {
    setProviderId(id);
    setModelId(providers.find((item) => item.id === id)?.models[0]?.id ?? "");
  }

  async function load(): Promise<void> {
    const preference = await api.preferences.current().catch(() => ({}));
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

    const allAgents = await api.agents.list();
    const visibleAgents = allAgents.filter((item) => !item.hidden && item.mode !== "subagent");
    setAgents(visibleAgents);

    if (clean.length === 0) {
      setProviderId("");
      setModelId("");
    } else {
      const preferredProviderId = typeof preference.provider_id === "string" ? preference.provider_id : "";
      const preferredModelId = typeof preference.model_id === "string" ? preference.model_id : "";
      if (preferredProviderId && preferredModelId && hasModel(clean, preferredProviderId, preferredModelId)) {
        setProviderId(preferredProviderId);
        setModelId(preferredModelId);
      } else {
        const first = firstModel(clean);
        setProviderId(first.providerId);
        setModelId(first.modelId);
      }
    }

    if (visibleAgents.length === 0) {
      setAgent("");
    } else {
      const preferredAgent = typeof preference.agent === "string" ? preference.agent : "";
      if (preferredAgent && visibleAgents.some((item) => item.name === preferredAgent)) {
        setAgent(preferredAgent);
      } else {
        setAgent(visibleAgents[0]!.name);
      }
    }
    setReady(true);
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!ready) {
      return;
    }
    const payload: { agent?: string; provider_id?: string; model_id?: string } = {};
    if (agent) {
      payload.agent = agent;
    }
    if (providerId && modelId) {
      payload.provider_id = providerId;
      payload.model_id = modelId;
    }
    if (Object.keys(payload).length === 0) {
      return;
    }
    void api.preferences.update(payload).catch(() => {});
  }, [ready, providerId, modelId, agent]);

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
