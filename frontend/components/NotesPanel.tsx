'use client';

import { useEffect, useState } from "react";
import { X, Plus, Trash2 } from "lucide-react";
import { LeadResponse, Note, fetchNotes, addNote, deleteNote } from "@/lib/api-client";
import { useI18n } from "@/lib/i18n";

interface NotesPanelProps {
  lead: LeadResponse;
  onClose: () => void;
}

export function NotesPanel({ lead, onClose }: NotesPanelProps) {
  const { t } = useI18n();
  const [notes, setNotes] = useState<Note[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchNotes(lead.id).then((n) => { setNotes(n); setLoading(false); }).catch(console.error);
  }, [lead.id]);

  const handleAdd = async () => {
    if (!text.trim()) return;
    const created = await addNote(lead.id, text.trim());
    setNotes((n) => [created, ...n]);
    setText("");
  };

  const handleDelete = async (noteId: number) => {
    await deleteNote(lead.id, noteId);
    setNotes((n) => n.filter((x) => x.id !== noteId));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div className="card w-full max-w-md p-6 animate-scale-in shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-5">
          <div>
            <h2 className="text-lg font-bold">{t("db.notes")}</h2>
            <p className="text-sm text-muted-foreground mt-0.5 truncate max-w-[16rem]">{lead.address}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex gap-2 mb-5">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            placeholder={t("db.note.placeholder")}
            className="h-10 flex-1 rounded-lg border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground px-4 text-sm font-medium transition"
          >
            <Plus className="h-4 w-4" /> {t("db.add")}
          </button>
        </div>

        <div className="space-y-2 max-h-72 overflow-y-auto scrollbar-thin pr-1">
          {loading ? (
            <p className="text-muted-foreground text-sm text-center py-6">{t("db.loading")}</p>
          ) : notes.length === 0 ? (
            <p className="text-muted-foreground text-sm text-center py-6">{t("db.note.placeholder")}</p>
          ) : (
            notes.map((n) => (
              <div key={n.id} className="group rounded-xl bg-muted p-3.5 flex justify-between items-start">
                <div>
                  <p className="text-sm">{n.note}</p>
                  <p className="text-xs text-muted-foreground mt-1" suppressHydrationWarning>
                    {new Date(n.created_at).toLocaleString("pt-BR")}
                  </p>
                </div>
                <button
                  onClick={() => handleDelete(n.id)}
                  className="text-muted-foreground hover:text-destructive p-1 rounded transition ml-2 opacity-60 group-hover:opacity-100"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
