import { useState, type FormEvent } from "react";
import { ArrowRight, Cloud, Eye, EyeOff, KeyRound, LockKeyhole, ShieldCheck, Sparkles } from "lucide-react";
import { desktopInvoke } from "../lib/desktop";

export type CloudAuthStatus = {
  connected: boolean;
  mode: string;
  base_url: string;
  user?: { email?: string };
};

type CloudLoginProps = {
  onConnected: (status: CloudAuthStatus) => void;
  onLocal: () => Promise<void>;
};

const DEFAULT_CLOUD_URL = "https://zerocode-cloud-api-2l3z.onrender.com";

export default function CloudLogin({ onConnected, onLocal }: CloudLoginProps) {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_CLOUD_URL);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [localBusy, setLocalBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await desktopInvoke<CloudAuthStatus & { ok: boolean }>("cloud_auth", {
        action: "login", email: email.trim(), password, baseUrl: baseUrl.trim()
      });
      setPassword("");
      onConnected(result);
    } catch (reason) {
      setError(String(reason).replace(/^Error: /, ""));
    } finally {
      setBusy(false);
    }
  };

  const continueLocally = async () => {
    if (localBusy) return;
    setLocalBusy(true);
    setError("");
    try { await onLocal(); }
    catch (reason) { setError(String(reason).replace(/^Error: /, "")); }
    finally { setLocalBusy(false); }
  };

  return (
    <div className="cloud-gate">
      <section className="cloud-gate-card">
        <aside className="cloud-gate-aside">
          <div className="cloud-gate-brand"><span className="cloud-gate-mark"><Sparkles size={19} /></span><strong>ZeroCode</strong><span>DESKTOP</span></div>
          <div className="cloud-gate-intro">
            <div className="cloud-gate-eyebrow"><span /> YOUR WORKSPACE, READY</div>
            <h1>Build more.<br /><em>Think bigger.</em></h1>
            <p>Un espace de développement intelligent, avec vos outils locaux et la puissance de ZeroCode Cloud.</p>
          </div>
          <div className="cloud-gate-security"><ShieldCheck size={17} /><span>Connexion sécurisée · Session partagée avec le TUI</span></div>
        </aside>

        <section className="cloud-gate-form-wrap">
          <div className="cloud-gate-heading">
            <div className="cloud-gate-icon"><Cloud size={21} /></div>
            <div><span className="cloud-gate-kicker">ZEROCode CLOUD</span><h2>Bienvenue</h2><p>Connectez-vous pour continuer.</p></div>
          </div>

          <form className="cloud-gate-form" onSubmit={submit}>
            <label>Serveur Cloud
              <input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://..." autoComplete="url" required />
            </label>
            <label>Adresse e-mail
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="vous@exemple.com" autoComplete="username" required />
            </label>
            <label>Mot de passe
              <div className="cloud-password-field">
                <LockKeyhole size={16} />
                <input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Votre mot de passe" autoComplete="current-password" required />
                <button type="button" aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"} onClick={() => setShowPassword((value) => !value)}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>
              </div>
            </label>
            {error && <div className="cloud-gate-error" role="alert">{error}</div>}
            <button className="cloud-gate-submit" type="submit" disabled={busy || !email.trim() || !password || !baseUrl.trim()}>
              {busy ? <><span className="spinner" /> Connexion…</> : <>Se connecter <ArrowRight size={17} /></>}
            </button>
          </form>

          <div className="cloud-gate-divider"><span />OU<span /></div>
          <button className="cloud-gate-local" type="button" onClick={continueLocally} disabled={localBusy}>
            <KeyRound size={16} /> {localBusy ? "Activation…" : "Continuer avec les fournisseurs locaux"}
          </button>
          <p className="cloud-gate-foot">Vos identifiants sont transmis directement au serveur configuré et la session est enregistrée dans le fichier protégé ZeroCode partagé avec le TUI.</p>
        </section>
      </section>
    </div>
  );
}
