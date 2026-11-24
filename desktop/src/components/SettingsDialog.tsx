import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Bot, Cpu, Database, ExternalLink, KeyRound, Keyboard, Palette, Save,
  ShieldCheck, SlidersHorizontal, Sparkles, Trash2, Users, X
} from "lucide-react";
import { Row, NumberField, Segmented, Toggle } from "./ui";
import { DEFAULT_RUNTIME, type Accent, type Settings, type ThinkLevel } from "../lib/settings";
import type { ProjectMemory, ProviderStatus, RuntimeSettings, SkillsState, SubagentRole } from "../types";

export type SettingsSection = "general" | "agent" | "providers" | "runtime" | "skills" | "subagents" | "interface" | "data";

const sections: Array<{ id: SettingsSection; label: string; icon: typeof Palette }> = [
  { id: "general", label: "Apparence", icon: Palette },
  { id: "agent", label: "Agent", icon: Bot },
  { id: "providers", label: "Fournisseurs & clés", icon: KeyRound },
  { id: "runtime", label: "Exécution", icon: Cpu },
  { id: "skills", label: "Skills & mémoire", icon: Sparkles },
  { id: "subagents", label: "Sous-agents", icon: Users },
  { id: "interface", label: "Interface", icon: SlidersHorizontal },
  { id: "data", label: "Données & raccourcis", icon: Database }
];

const accents: Array<{ id: Accent; label: string; color: string }> = [
  { id: "blue", label: "Bleu", color: "#4c8dff" },
  { id: "violet", label: "Violet", color: "#8b6cf6" },
  { id: "green", label: "Vert", color: "#2fb582" },
  { id: "orange", label: "Orange", color: "#f08c3a" },
  { id: "rose", label: "Rose", color: "#ec5f93" }
];

const shortcuts: Array<[string, string]> = [
  ["Ctrl K", "Palette de commandes"],
  ["Ctrl N", "Nouvelle tâche"],
  ["Ctrl B", "Afficher/masquer la barre latérale"],
  ["Ctrl I", "Afficher/masquer l’inspecteur"],
  ["Ctrl `", "Afficher/masquer le terminal"],
  ["Ctrl ,", "Préférences"],
  ["/", "Commandes rapides (/agent, /skill, /remember…)"],
  ["@", "Mentionner un fichier du projet"],
  ["Échap", "Fermer les fenêtres"]
];

export interface SettingsDialogProps {
  initialSection?: SettingsSection;
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
  reset: () => void;
  onClose: () => void;
  ready: boolean;
  busy: boolean;
  workspace: string | null;
  mode: string;
  model: string;
  availableModels: string[];
  permissionsMode: string;
  thinkMode: string;
  runtime: RuntimeSettings | null;
  roles: SubagentRole[];
  skills: SkillsState;
  memory: ProjectMemory;
  providers: ProviderStatus[];
  onMode: (mode: string) => void;
  onModel: (model: string) => void;
  onPermissions: (mode: string) => void;
  onThink: (think: ThinkLevel) => void;
  onRuntime: (patch: Partial<RuntimeSettings>) => void;
  onToggleSkill: (name: string) => void;
  onSaveMemory: (content: string) => void;
  onSaveProviderKey: (provider: string, key: string) => void;
  onDeleteProviderKey: (provider: string) => void;
  onCompact: () => void;
  onCopyConversation: () => void;
  onClearRecents: () => void;
}

export default function SettingsDialog(props: SettingsDialogProps) {
  const { settings, update, ready, busy, runtime, roles, skills, memory, providers } = props;
  const [section, setSection] = useState<SettingsSection>(props.initialSection ?? "general");
  const [customModel, setCustomModel] = useState("");
  const [skillQuery, setSkillQuery] = useState("");
  const [memoryDraft, setMemoryDraft] = useState(memory.content);
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    if (props.initialSection) setSection(props.initialSection);
  }, [props.initialSection]);

  useEffect(() => {
    setMemoryDraft(memory.content);
  }, [memory.content]);

  const locked = !ready || busy;
  const effective: RuntimeSettings = runtime ?? { ...DEFAULT_RUNTIME, ...settings.runtime };
  const setRuntime = (patch: Partial<RuntimeSettings>) => {
    update({ runtime: { ...settings.runtime, ...patch } });
    props.onRuntime(patch);
  };

  const filteredSkills = useMemo(() => {
    const q = skillQuery.trim().toLowerCase();
    if (!q) return skills.available;
    return skills.available.filter((item) =>
      `${item.id} ${item.label} ${item.category} ${item.summary}`.toLowerCase().includes(q)
    );
  }, [skills.available, skillQuery]);

  return (
    <div className="overlay" onMouseDown={props.onClose}>
      <motion.div className="dialog settings-dialog" role="dialog" aria-modal="true" aria-label="Préférences"
        onMouseDown={(event) => event.stopPropagation()}
        initial={{ opacity: 0, y: 10, scale: 0.985 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.16 }}>
        <nav className="settings-nav">
          <div className="settings-title">Préférences</div>
          {sections.map(({ id, label, icon: Icon }) => (
            <button type="button" key={id} className={section === id ? "active" : ""} onClick={() => setSection(id)}>
              <Icon size={15} /> {label}
            </button>
          ))}
        </nav>

        <div className="settings-body">
          <button type="button" className="icon-btn settings-close" onClick={props.onClose} aria-label="Fermer"><X size={16} /></button>

          {section === "general" && (
            <>
              <h2>Apparence</h2>
              <Row title="Thème" hint="« Système » suit le réglage de votre ordinateur.">
                <Segmented label="Thème" value={settings.theme} onChange={(theme) => update({ theme })}
                  options={[{ id: "system", label: "Système" }, { id: "light", label: "Clair" }, { id: "dark", label: "Sombre" }]} />
              </Row>
              <Row title="Couleur d’accent">
                <div className="swatches">
                  {accents.map((item) => (
                    <button type="button" key={item.id} title={item.label} aria-label={item.label}
                      className={settings.accent === item.id ? "swatch active" : "swatch"}
                      style={{ background: item.color }} onClick={() => update({ accent: item.id })} />
                  ))}
                </div>
              </Row>
              <Row title="Densité" hint="Compacte réduit les marges pour afficher plus de contenu.">
                <Segmented label="Densité" value={settings.density} onChange={(density) => update({ density })}
                  options={[{ id: "comfortable", label: "Confortable" }, { id: "compact", label: "Compacte" }]} />
              </Row>
              <Row title="Taille du texte" hint={`${settings.fontSize} px`}>
                <input className="range" type="range" min={12} max={17} step={1} value={settings.fontSize}
                  aria-label="Taille du texte" onChange={(event) => update({ fontSize: Number(event.target.value) })} />
              </Row>
            </>
          )}

          {section === "agent" && (
            <>
              <h2>Agent</h2>
              <Row title="Mode de travail" hint="Plan lit sans modifier. Build agit avec autorisation. Full-stack planifie, délègue et vérifie.">
                <Segmented label="Mode" value={props.mode} disabled={locked} onChange={props.onMode}
                  options={[{ id: "build", label: "Build" }, { id: "plan", label: "Plan" }, { id: "full-stack", label: "Full-stack" }]} />
              </Row>
              <Row title="Autorisations des outils" hint="Réinitialisé sur « Demander » à chaque lancement pour votre sécurité." stacked>
                <div className="choice-grid">
                  {[
                    { id: "ask", label: "Demander", desc: "Confirmation avant écriture ou commande" },
                    { id: "auto", label: "Auto-édition", desc: "Éditions sûres dans le projet sans confirmation" },
                    { id: "allow", label: "Autonome", desc: "Exécute sans interrompre, hors actions critiques" }
                  ].map((option) => (
                    <button type="button" key={option.id} disabled={locked}
                      className={props.permissionsMode === option.id ? "choice active" : "choice"}
                      onClick={() => props.onPermissions(option.id)}>
                      <strong>{option.label}</strong><span>{option.desc}</span>
                    </button>
                  ))}
                </div>
              </Row>
              <Row title="Modèle actif" hint="« auto » choisit la meilleure route disponible." stacked>
                <select value={props.availableModels.includes(props.model) ? props.model : "__custom__"} disabled={locked}
                  onChange={(event) => { if (event.target.value !== "__custom__") props.onModel(event.target.value); }}>
                  {props.availableModels.map((item) => <option key={item} value={item}>{item === "auto" ? "auto — routage intelligent" : item}</option>)}
                  {!props.availableModels.includes(props.model) && <option value="__custom__">{props.model}</option>}
                </select>
                <div className="inline-form">
                  <input placeholder="Identifiant personnalisé (ex. ollama/qwen2.5-coder)" value={customModel}
                    onChange={(event) => setCustomModel(event.target.value)} />
                  <button type="button" className="btn primary" disabled={locked || !customModel.trim()}
                    onClick={() => { props.onModel(customModel.trim()); setCustomModel(""); }}>Appliquer</button>
                </div>
              </Row>
              <Row title="Profondeur de raisonnement">
                <Segmented label="Raisonnement" value={(props.thinkMode as ThinkLevel) || "off"} disabled={locked} onChange={props.onThink}
                  options={(["off", "low", "high", "max"] as const).map((id) => ({ id, label: id.toUpperCase() }))} />
              </Row>
              <h3>Au démarrage</h3>
              <Row title="Mode par défaut" hint="Full-stack n’est jamais restauré automatiquement.">
                <Segmented label="Mode par défaut" value={settings.defaultMode} onChange={(defaultMode) => update({ defaultMode })}
                  options={[{ id: "build", label: "Build" }, { id: "plan", label: "Plan" }]} />
              </Row>
              <Row title="Modèle préféré" hint="Vide : garder celui de la session.">
                <input className="text-input" placeholder="auto" value={settings.preferredModel}
                  onChange={(event) => update({ preferredModel: event.target.value })} />
              </Row>
              <Row title="Raisonnement par défaut">
                <Segmented label="Raisonnement par défaut" value={settings.preferredThink} onChange={(preferredThink) => update({ preferredThink })}
                  options={(["off", "low", "high", "max"] as const).map((id) => ({ id, label: id.toUpperCase() }))} />
              </Row>
            </>
          )}

          {section === "providers" && (
            <>
              <h2>Fournisseurs & clés API</h2>
              <p className="section-note">Les clés enregistrées ici sont stockées localement dans le coffre ZeroCode (droits <code>0600</code>) et ne sont jamais réaffichées en clair.</p>
              {providers.length === 0 ? (
                <p className="muted-note">Connectez l’agent pour gérer les fournisseurs.</p>
              ) : (
                <div className="provider-list">
                  {providers.map((item) => {
                    const draftKey = keyDrafts[item.id] ?? "";
                    const statusText = item.source === "keyless" ? "Sans clé"
                      : item.source === "env" ? `Variable ${item.env_var}`
                      : item.source === "store" ? `Coffre (${item.key_masked})`
                      : "Non configuré";
                    return (
                      <article key={item.id} className="provider-card">
                        <div className="provider-head">
                          <div>
                            <strong>{item.label}</strong>
                            <span className="provider-sub">{item.id} · {item.models_count} modèle(s)</span>
                          </div>
                          <span className={"provider-pill " + (item.available ? "ok" : "off")}>{statusText}</span>
                        </div>
                        {item.notes && <p className="provider-note">{item.notes}</p>}
                        {item.requires_key && (
                          <form className="inline-form" onSubmit={(event) => {
                            event.preventDefault();
                            if (!draftKey.trim() || !ready) return;
                            props.onSaveProviderKey(item.id, draftKey.trim());
                            setKeyDrafts((prev) => ({ ...prev, [item.id]: "" }));
                          }}>
                            <input type="password" autoComplete="off" value={draftKey} disabled={!ready}
                              placeholder={item.source === "store" ? "Remplacer la clé API…" : `Clé API (${item.env_var})…`}
                              onChange={(event) => setKeyDrafts((prev) => ({ ...prev, [item.id]: event.target.value }))} />
                            <button type="submit" className="btn small primary" disabled={!ready || !draftKey.trim()}>Enregistrer</button>
                            {item.source === "store" && (
                              <button type="button" className="btn small danger" disabled={!ready} title="Supprimer du coffre"
                                onClick={() => props.onDeleteProviderKey(item.id)}><Trash2 size={13} /></button>
                            )}
                          </form>
                        )}
                        {item.signup_url && (
                          <a className="provider-link" href={item.signup_url} target="_blank" rel="noreferrer">
                            Obtenir une clé <ExternalLink size={11} />
                          </a>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {section === "runtime" && (
            <>
              <h2>Exécution</h2>
              <p className="section-note">Ces réglages sont appliqués à chaud et rappliqués à chaque démarrage de l’agent.</p>
              <Row title="Étapes maximum par tâche" hint="Limite de la boucle outil → réponse.">
                <NumberField value={effective.max_steps} min={1} max={500} disabled={locked} onCommit={(max_steps) => setRuntime({ max_steps })} />
              </Row>
              <Row title="Délai des commandes" hint="Durée maximale d’une commande shell.">
                <NumberField value={effective.command_timeout} min={1} max={3600} suffix="s" disabled={locked} onCommit={(command_timeout) => setRuntime({ command_timeout })} />
              </Row>
              <Row title="Jetons de sortie maximum">
                <NumberField value={effective.max_tokens} min={256} max={128000} step={256} disabled={locked} onCommit={(max_tokens) => setRuntime({ max_tokens })} />
              </Row>
              <Row title="Créativité (température)" hint="0 = déterministe, 2 = très varié.">
                <NumberField value={effective.temperature} min={0} max={2} step={0.1} disabled={locked} onCommit={(temperature) => setRuntime({ temperature })} />
              </Row>
              <Row title="Seuil de compaction" hint="Part du contexte utilisée avant résumé automatique.">
                <NumberField value={effective.compact_threshold} min={0.2} max={0.95} step={0.05} disabled={locked} onCommit={(compact_threshold) => setRuntime({ compact_threshold })} />
              </Row>
              <Row title="Compaction automatique"><Toggle label="Compaction automatique" checked={effective.auto_compact} disabled={locked} onChange={(auto_compact) => setRuntime({ auto_compact })} /></Row>
              <Row title="Routage selon la tâche" hint="Choisit un modèle adapté (code, audit, requête simple)."><Toggle label="Routage selon la tâche" checked={effective.task_routing} disabled={locked} onChange={(task_routing) => setRuntime({ task_routing })} /></Row>
              <Row title="Repli automatique" hint="Bascule vers un autre modèle s’il est saturé ou indisponible."><Toggle label="Repli automatique" checked={effective.fallback} disabled={locked} onChange={(fallback) => setRuntime({ fallback })} /></Row>
              <Row title="Modèles gratuits uniquement"><Toggle label="Modèles gratuits uniquement" checked={effective.free_only} disabled={locked} onChange={(free_only) => setRuntime({ free_only })} /></Row>
              <Row title="Afficher les diffs de modification"><Toggle label="Afficher les diffs" checked={effective.diff_view} disabled={locked} onChange={(diff_view) => setRuntime({ diff_view })} /></Row>
              <p className="settings-callout"><ShieldCheck size={14} /> L’accès hors du projet et la protection des secrets ne sont volontairement pas modifiables depuis l’interface.</p>
            </>
          )}

          {section === "skills" && (
            <>
              <h2>Skills d’expertise</h2>
              <p className="section-note">Activez les compétences injectées dans le prompt système ({skills.active.length} actif(s) sur {skills.available.length}). Commande rapide : <code>/skill &lt;nom&gt;</code>.</p>
              <div className="inline-form">
                <input className="text-input" placeholder="Filtrer les skills (ex. dev, security, fabric…)" value={skillQuery} onChange={(event) => setSkillQuery(event.target.value)} />
                <button type="button" className="btn small" disabled={locked} onClick={() => props.onToggleSkill("default")}>Par défaut</button>
                <button type="button" className="btn small" disabled={locked} onClick={() => props.onToggleSkill("none")}>Aucun</button>
              </div>
              <div className="skill-list">
                {filteredSkills.map((item) => {
                  const active = skills.active.includes(item.id);
                  return (
                    <div key={item.id} className={"skill-row" + (active ? " active" : "")}>
                      <div className="skill-copy">
                        <strong>{item.id} <em>{item.category}{item.builtin ? "" : " · perso"}</em></strong>
                        <span>{item.summary}</span>
                      </div>
                      <Toggle label={`Skill ${item.id}`} checked={active} disabled={locked} onChange={() => props.onToggleSkill(item.id)} />
                    </div>
                  );
                })}
                {filteredSkills.length === 0 && <p className="muted-note">Aucun skill correspondant.</p>}
              </div>

              <h3>Mémoire projet ({memory.path})</h3>
              {props.workspace ? (
                <>
                  <p className="section-note">Ces consignes sont injectées automatiquement à chaque session dans ce projet. Les secrets connus sont masqués.</p>
                  <textarea className="task-input memory-editor" rows={7} value={memoryDraft} disabled={!ready}
                    placeholder="# Instructions projet ZeroCode&#10;- Toujours lancer pytest avant de conclure&#10;- Respecter le style TypeScript strict"
                    onChange={(event) => setMemoryDraft(event.target.value)} />
                  <div className="inline-actions">
                    <button type="button" className="btn small primary" disabled={!ready || memoryDraft === memory.content}
                      onClick={() => props.onSaveMemory(memoryDraft)}>
                      <Save size={13} /> Enregistrer la mémoire
                    </button>
                  </div>
                </>
              ) : (
                <p className="muted-note">Ouvrez un dossier de projet pour éditer sa mémoire persistante.</p>
              )}
            </>
          )}

          {section === "subagents" && (
            <>
              <h2>Sous-agents</h2>
              <p className="section-note">Les sous-agents sont des spécialistes isolés en lecture seule exécutés en parallèle : ils explorent, analysent et rendent une synthèse. L’agent principal reste seul responsable des modifications.</p>
              <Row title="Déléguer automatiquement" hint="Ajoute une consigne invitant l’agent à confier les analyses indépendantes à des spécialistes.">
                <Toggle label="Déléguer automatiquement" checked={settings.autoDelegate} onChange={(autoDelegate) => update({ autoDelegate })} />
              </Row>
              <Row title="Spécialiste par défaut" hint="Utilisé par la commande /agent et le panneau Agents.">
                <select value={settings.defaultSubagentRole} onChange={(event) => update({ defaultSubagentRole: event.target.value })}>
                  {(roles.length ? roles : [{ id: settings.defaultSubagentRole, description: "" }]).map((role) => <option key={role.id} value={role.id}>{role.id}</option>)}
                </select>
              </Row>
              <div className="role-list">
                {roles.map((role) => (
                  <div className="role-item" key={role.id}><strong>{role.id}</strong><span>{role.description}</span></div>
                ))}
              </div>
            </>
          )}

          {section === "interface" && (
            <>
              <h2>Interface</h2>
              <Row title="Envoyer le message avec">
                <Segmented label="Touche d’envoi" value={settings.sendKey} onChange={(sendKey) => update({ sendKey })}
                  options={[{ id: "enter", label: "Entrée" }, { id: "mod-enter", label: "Ctrl + Entrée" }]} />
              </Row>
              <Row title="Défilement automatique" hint="Suivre la réponse pendant sa rédaction."><Toggle label="Défilement automatique" checked={settings.autoScroll} onChange={(autoScroll) => update({ autoScroll })} /></Row>
              <Row title="Afficher le raisonnement de l’agent"><Toggle label="Afficher le raisonnement" checked={settings.showReasoning} onChange={(showReasoning) => update({ showReasoning })} /></Row>
              <Row title="Détails des appels d’outils" hint="Arguments et sorties dépliables dans la conversation."><Toggle label="Détails des outils" checked={settings.showToolDetails} onChange={(showToolDetails) => update({ showToolDetails })} /></Row>
              <Row title="Confirmer les modes à risque" hint="Demande une confirmation avant Full-stack ou Autonome."><Toggle label="Confirmer les modes à risque" checked={settings.confirmRiskyModes} onChange={(confirmRiskyModes) => update({ confirmRiskyModes })} /></Row>
              <Row title="Notifier à la fin d’une tâche" hint="Notification système quand la fenêtre n’est pas au premier plan.">
                <Toggle label="Notifier à la fin d’une tâche" checked={settings.notifyOnDone} onChange={(notifyOnDone) => {
                  update({ notifyOnDone });
                  if (notifyOnDone && "Notification" in window && Notification.permission === "default") void Notification.requestPermission();
                }} />
              </Row>
            </>
          )}

          {section === "data" && (
            <>
              <h2>Données & raccourcis</h2>
              <Row title="Compacter le contexte" hint="Résume la conversation pour libérer de la place."><button type="button" className="btn" disabled={locked} onClick={props.onCompact}>Compacter</button></Row>
              <Row title="Copier la conversation" hint="Au format Markdown."><button type="button" className="btn" onClick={props.onCopyConversation}>Copier</button></Row>
              <Row title="Projets récents"><button type="button" className="btn" onClick={props.onClearRecents}>Effacer</button></Row>
              <Row title="Réinitialiser les préférences" hint="Rétablit les valeurs par défaut de cette page."><button type="button" className="btn danger" onClick={() => { if (window.confirm("Réinitialiser toutes les préférences de l’interface ?")) props.reset(); }}>Réinitialiser</button></Row>
              <h3><Keyboard size={14} /> Raccourcis</h3>
              <div className="shortcut-list">
                {shortcuts.map(([key, label]) => <div key={key}><kbd>{key}</kbd><span>{label}</span></div>)}
              </div>
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}
