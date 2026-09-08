'use client';

import { LeadResponse } from "@/lib/api-client";

interface LeadCardProps {
  lead: LeadResponse;
}

export function LeadCard({ lead }: LeadCardProps) {
  return (
    <div className="bg-white border rounded-lg p-4 shadow-sm hover:shadow-md transition">
      <div className="flex justify-between items-start mb-2">
        <h3 className="font-semibold text-sm">{lead.address}</h3>
        <span className="inline-block bg-orange-100 text-orange-800 px-2 py-1 rounded text-xs font-medium">
          {lead.issue_category}
        </span>
      </div>

      <p className="text-gray-600 text-sm mb-2">{lead.issue_description}</p>

      <div className="text-xs text-gray-500 space-y-1">
        {lead.owner_name && <p>Proprietário: {lead.owner_name}</p>}
        {lead.owner_phone && <p>Telefone: {lead.owner_phone}</p>}
        <p suppressHydrationWarning>Data: {new Date(lead.date_reported).toLocaleDateString("pt-BR")}</p>
      </div>
    </div>
  );
}