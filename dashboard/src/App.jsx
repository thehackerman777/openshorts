import React, { useState, useEffect } from 'react';
import { Youtube, Settings, Image, AlertTriangle, CheckCircle2, KeyRound, Shield } from 'lucide-react';
import KeyInput from './components/KeyInput';
import ThumbnailStudio from './components/ThumbnailStudio';
import { getApiUrl } from './config';

const SESSION_KEY = 'openshorts_session';

function App() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  const [youtubeConnected, setYoutubeConnected] = useState(false);
  const [youtubeAuthCode, setYoutubeAuthCode] = useState("");
  const [showYoutubeCodeInput, setShowYoutubeCodeInput] = useState(false);
  const [activeTab, setActiveTab] = useState('thumbnails'); // thumbnails, settings
  const [showKeyModal, setShowKeyModal] = useState(false);

  // Check YouTube auth status on mount and when tab changes
  useEffect(() => {
    fetch(getApiUrl('/auth/youtube/status'))
      .then(r => r.json())
      .then(d => setYoutubeConnected(d.authenticated))
      .catch(() => {});
  }, [activeTab]);

  // Sync DeepSeek Key to localStorage
  useEffect(() => {
    if (apiKey) {
      localStorage.setItem('gemini_key', apiKey);
    } else {
      localStorage.removeItem('gemini_key');
    }
  }, [apiKey]);

  // Mandatory setup validation: If no API key configured, force settings tab
  useEffect(() => {
    if (!apiKey) {
      setActiveTab('settings');
    }
  }, [apiKey]);

  const handleYoutubeConnect = async () => {
    try {
      const res = await fetch(getApiUrl('/auth/youtube/login'));
      const data = await res.json();
      if (data.auth_url) window.open(data.auth_url, '_blank');
      setShowYoutubeCodeInput(true);
    } catch(e) {
      console.error('YouTube connect failed:', e);
    }
  };

  const handleYoutubeExchangeCode = async () => {
    if (!youtubeAuthCode.trim()) return;
    try {
      const fd = new FormData();
      fd.append('code', youtubeAuthCode.trim());
      const res = await fetch(getApiUrl('/auth/youtube/exchange'), { method: 'POST', body: fd });
      if (res.ok) {
        setYoutubeConnected(true);
        setShowYoutubeCodeInput(false);
        setYoutubeAuthCode("");
      } else {
        alert('Failed to connect YouTube. Check the code.');
      }
    } catch(e) {
      console.error('Exchange failed:', e);
    }
  };

  // Sidebar Component
  const Sidebar = () => (
    <div className="w-20 lg:w-64 bg-surface border-r border-white/5 flex flex-col h-full shrink-0 transition-all duration-300">
      <div className="p-6 flex items-center gap-3">
        <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center shrink-0 overflow-hidden border border-white/5">
          <img src="/logo-openshorts.png" alt="Logo" className="w-full h-full object-cover" />
        </div>
        <span className="font-bold text-lg text-white hidden lg:block tracking-tight">OpenShorts</span>
      </div>

      <nav className="flex-1 px-4 py-4 space-y-2">
        <button
          onClick={() => apiKey && setActiveTab('thumbnails')}
          disabled={!apiKey}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${
            !apiKey 
              ? 'opacity-40 cursor-not-allowed text-zinc-600' 
              : (activeTab === 'thumbnails' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5')
          }`}
          title={!apiKey ? "Configure la clave API de DeepSeek primero" : "YouTube Studio"}
        >
          <Image size={20} />
          <span className="font-medium hidden lg:block">YouTube Studio</span>
        </button>

        <button
          onClick={() => setActiveTab('settings')}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl transition-colors ${
            activeTab === 'settings' ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/5'
          }`}
        >
          <Settings size={20} />
          <span className="font-medium hidden lg:block">Configuración</span>
        </button>
      </nav>

      <div className="p-4 border-t border-white/5">
        <div className="text-zinc-600 text-[10px] text-center hidden lg:block">
          OpenShorts v2.0 - Studio Edition
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-background overflow-hidden selection:bg-primary/30">
      <Sidebar />

      <main className="flex-1 flex flex-col h-full overflow-hidden relative">
        {/* Background Gradients */}
        <div className="absolute inset-0 overflow-hidden -z-10 pointer-events-none">
          <div className="absolute -top-[10%] -right-[10%] w-[50%] h-[50%] bg-primary/5 rounded-full blur-[120px]" />
        </div>

        {/* Top Header */}
        <header className="h-16 border-b border-white/5 bg-background/50 backdrop-blur-md flex items-center justify-between px-6 shrink-0 z-10">
          <div className="flex items-center gap-4">
            <span className="text-sm font-semibold text-zinc-400">Panel de Control</span>
          </div>

          <div className="flex items-center gap-4">
            {!apiKey && (
              <button
                onClick={() => setActiveTab('settings')}
                className="text-xs text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 px-3 py-1.5 rounded-full border border-amber-500/30 transition-colors flex items-center gap-1.5 animate-pulse"
                title="Clave API de DeepSeek faltante"
              >
                <AlertTriangle size={12} />
                Clave DeepSeek Faltante
              </button>
            )}
            {apiKey && !youtubeConnected && (
              <button
                onClick={() => setActiveTab('settings')}
                className="text-xs text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 px-3 py-1.5 rounded-full border border-amber-500/30 transition-colors flex items-center gap-1.5"
                title="YouTube no conectado"
              >
                <AlertTriangle size={12} />
                YouTube Desconectado
              </button>
            )}
            {apiKey && youtubeConnected && (
              <span className="text-xs text-green-400 bg-green-500/10 px-3 py-1.5 rounded-full border border-green-500/30 flex items-center gap-1.5">
                <CheckCircle2 size={12} className="text-green-400" />
                YouTube Conectado
              </span>
            )}
          </div>
        </header>

        {/* Persistent Missing Keys Banner */}
        {!apiKey && activeTab !== 'settings' && (
          <div className="mx-6 mt-3 p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center justify-between gap-4 shrink-0 animate-[fadeIn_0.3s_ease-out]">
            <div className="flex items-center gap-3 text-sm text-amber-200">
              <KeyRound size={16} className="shrink-0 text-amber-400" />
              <div>
                <span className="font-semibold">Se requiere la clave API de DeepSeek.</span>{' '}
                <span className="text-amber-200/80">
                  Por favor, configura tu clave API de DeepSeek en Configuración para comenzar.
                </span>
              </div>
            </div>
            <button
              onClick={() => setActiveTab('settings')}
              className="shrink-0 text-xs font-medium px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-black transition-colors"
            >
              Configurar
            </button>
          </div>
        )}

        {/* Main Workspace */}
        <div className="flex-1 overflow-hidden relative">

          {/* View: Settings */}
          {activeTab === 'settings' && (
            <div className="h-full overflow-y-auto p-8 max-w-2xl mx-auto animate-[fadeIn_0.3s_ease-out]">
              <div className="flex items-center justify-between mb-8">
                <h1 className="text-2xl font-bold">Configuración</h1>
                <div className="px-3 py-1 bg-green-500/10 border border-green-500/20 rounded-full text-[10px] text-green-400 font-medium flex items-center gap-2">
                  <Shield size={12} /> Privacidad: las claves residen solo en tu navegador
                </div>
              </div>
              
              <KeyInput onKeySet={setApiKey} savedKey={apiKey} />

              <div className="glass-panel p-6 mt-8 border-red-500/30 ring-1 ring-red-500/20">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Publicación en YouTube</h2>
                  <span className={`text-[10px] px-2 py-0.5 rounded uppercase tracking-wider ${youtubeConnected ? 'bg-green-500/10 border border-green-500/30 text-green-400' : 'bg-amber-500/10 border border-amber-500/30 text-amber-400'}`}>
                    {youtubeConnected ? 'Conectado' : 'No conectado'}
                  </span>
                </div>
                <p className="text-xs text-zinc-500 mb-6 leading-relaxed">
                  Publica vídeos directamente en tu canal de YouTube de manera <strong>nativa</strong> sin servicios externos.
                  Utiliza el protocolo seguro OAuth 2.0 y la API oficial de YouTube.
                </p>
                <div className="space-y-4">
                  <div className="flex gap-2">
                    <button
                      onClick={handleYoutubeConnect}
                      disabled={youtubeConnected}
                      className="bg-red-500/20 border border-red-500/30 px-4 py-2 rounded-lg text-sm font-medium text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50 flex items-center gap-2"
                    >
                      <Youtube size={16} />
                      {youtubeConnected ? 'Conectado' : 'Conectar YouTube'}
                    </button>
                    {youtubeConnected && (
                      <span className="text-xs text-green-400 flex items-center">Autorizado</span>
                    )}
                  </div>
                  
                  {showYoutubeCodeInput && !youtubeConnected && (
                    <div className="p-3 bg-white/5 border border-white/10 rounded-lg space-y-2">
                      <p className="text-xs text-zinc-400">
                        Tras la autorización en Google, copia la URL completa de la barra de direcciones de tu navegador y pégala aquí abajo:
                      </p>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={youtubeAuthCode}
                          onChange={(e) => setYoutubeAuthCode(e.target.value)}
                          placeholder="Pega la URL de redirección aquí..."
                          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-primary/50"
                        />
                        <button onClick={handleYoutubeExchangeCode} className="px-4 py-2 bg-primary/20 border border-primary/30 rounded-lg text-primary text-xs font-medium hover:bg-primary/30">
                          Conectar
                        </button>
                      </div>
                    </div>
                  )}

                  <p className="text-xs text-zinc-500 leading-relaxed">
                    <strong>Paso previo:</strong> En Google Cloud Console, crea credenciales de tipo "ID de cliente OAuth" con la siguiente URI de redirección autorizada:<br />
                    <code className="text-primary text-[10px] bg-white/5 px-2 py-0.5 rounded">http://localhost:8000/auth/youtube/callback</code>
                    <br />Luego descarga el archivo JSON de credenciales, cámbiale el nombre a <code className="text-primary text-[10px]">youtube_client_secrets.json</code> y colócalo en la carpeta <code className="text-primary text-[10px]">data/</code> del proyecto.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* View: YouTube Studio */}
          {activeTab === 'thumbnails' && apiKey && (
            <ThumbnailStudio 
              geminiApiKey={apiKey} 
              youtubeConnected={youtubeConnected} 
              onGoToSettings={() => setActiveTab('settings')}
            />
          )}

        </div>

      </main>

      {/* Missing API Key Modal */}
      {showKeyModal && !apiKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#18181b] border border-white/10 rounded-2xl p-6 max-w-md w-full mx-4 space-y-4 shadow-2xl">
            <h2 className="text-lg font-bold text-white">
              Se Requiere la API Key de DeepSeek
            </h2>
            <p className="text-sm text-zinc-400">
              OpenShorts necesita una clave API de <strong className="text-zinc-200">DeepSeek</strong> para sugerir títulos optimizados y descripciones con capítulos automáticos.
            </p>

            <div className="rounded-lg p-4 space-y-2 border bg-blue-500/5 border-blue-500/30">
              <p className="text-xs font-semibold text-zinc-200 flex items-center gap-2">
                <AlertTriangle size={12} className="text-amber-400" />
                Clave API de DeepSeek
              </p>
              <ol className="text-xs text-zinc-400 space-y-1 list-decimal list-inside">
                <li>Ve a <a href="https://platform.deepseek.com/" target="_blank" rel="noopener noreferrer" className="text-blue-400 underline">platform.deepseek.com</a></li>
                <li>Inicia sesión y crea una clave en la sección "API Keys"</li>
                <li>Pega la clave abajo y presiona Enter</li>
              </ol>
              <input
                type="text"
                placeholder="Introduce tu clave API de DeepSeek (sk-...)"
                className="w-full bg-black/50 border border-white/20 rounded-lg px-4 py-2.5 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && e.target.value.trim()) {
                    setApiKey(e.target.value.trim());
                    setShowKeyModal(false);
                  }
                }}
              />
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => { setShowKeyModal(false); setActiveTab('settings'); }}
                className="flex-1 text-sm text-white py-2 rounded-lg bg-blue-600 hover:bg-blue-500 transition-colors font-medium"
              >
                Ir a Configuración
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
