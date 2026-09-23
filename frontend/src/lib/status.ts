export const ROTULOS_STATUS: Record<string, string> = {
  aguardando_emissao: "Aguardando emissão",
  pendente: "Pendente",
  autorizada: "Autorizada",
  rejeitada: "Rejeitada",
  cancelada: "Cancelada",
  cancelamento_pendente: "Cancelamento pendente",
  erro_cancelamento: "Erro no cancelamento",
  aguardando_confirmacao: "Aguardando confirmação",
  cancelamento_aguardando_confirmacao: "Cancel. aguardando confirmação",
};

export const CLASSES_PILULA: Record<string, string> = {
  aguardando_emissao: "rascunho",
  autorizada: "autorizada",
  rejeitada: "rejeitada",
  erro_cancelamento: "rejeitada",
  cancelada: "cancelada",
  pendente: "pendente",
  cancelamento_pendente: "pendente",
  aguardando_confirmacao: "pendente",
  cancelamento_aguardando_confirmacao: "pendente",
};

// Cores hexadecimais equivalentes as classes de pilula (CSS var --status-*),
// usadas no grafico/legenda do Painel, onde nao da pra aplicar uma classe CSS.
export const CORES_STATUS: Record<string, string> = {
  aguardando_emissao: "#5b6b70",
  autorizada: "#1f7a5e",
  rejeitada: "#a32219",
  erro_cancelamento: "#a32219",
  cancelada: "#5b6b70",
  pendente: "#8a5a0a",
  cancelamento_pendente: "#8a5a0a",
  aguardando_confirmacao: "#8a5a0a",
  cancelamento_aguardando_confirmacao: "#8a5a0a",
};
