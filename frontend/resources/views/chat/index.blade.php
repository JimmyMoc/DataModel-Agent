<!DOCTYPE html>
<html lang="es" class="h-full" x-data x-bind:class="{ 'dark': $store.theme.dark }">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <title>Data Model Agent</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        dark: {
                            50: '#f8fafc',
                            100: '#f1f5f9',
                            700: '#1e293b',
                            800: '#0f172a',
                            900: '#020617',
                        }
                    }
                }
            }
        }
    </script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <script>
        document.addEventListener('alpine:init', () => {
            Alpine.store('theme', {
                dark: localStorage.getItem('theme') !== 'light',
                toggle() {
                    this.dark = !this.dark;
                    localStorage.setItem('theme', this.dark ? 'dark' : 'light');
                }
            });
        });
    </script>
    <link id="hljs-theme" rel="stylesheet"
        href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/sql.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/json.min.js"></script>
    <style>
        [x-cloak] {
            display: none !important;
        }

        .typing-dot {
            animation: typing 1.4s infinite;
        }

        .typing-dot:nth-child(2) {
            animation-delay: 0.2s;
        }

        .typing-dot:nth-child(3) {
            animation-delay: 0.4s;
        }

        @keyframes typing {

            0%,
            60%,
            100% {
                opacity: 0.3;
                transform: translateY(0);
            }

            30% {
                opacity: 1;
                transform: translateY(-4px);
            }
        }

        .message-enter {
            animation: slideUp 0.3s ease-out;
        }

        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(10px);
            }

            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        pre code {
            border-radius: 0.5rem;
        }
    </style>
</head>

<body class="h-full bg-white dark:bg-dark-900 text-gray-900 dark:text-gray-100 transition-colors duration-200"
    x-data="chatApp()" x-init="init()">

    <div class="flex h-full">
        <!-- ═══ Sidebar ═══ -->
        <aside class="w-72 bg-gray-50 dark:bg-dark-800 border-r border-gray-200 dark:border-gray-700/50 flex flex-col"
            x-show="showSidebar" x-cloak>
            <!-- Header -->
            <div class="p-4 border-b border-gray-200 dark:border-gray-700/50">
                <div class="flex items-center gap-2 mb-4">
                    <h1 class="text-lg font-bold text-gray-900 dark:text-white">Data Model Agent</h1>
                </div>
                <button @click="newConversation()"
                    class="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition">
                    + Nueva conversación
                </button>
            </div>

            <!-- Conversations list -->
            <div class="flex-1 overflow-y-auto p-2">
                <template x-for="conv in conversations" :key="conv.id">
                    <div class="relative group mb-1">
                        <button @click="loadConversation(conv.id)"
                            :class="conversationId === conv.id ? 'bg-gray-200 dark:bg-gray-700/50 text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700/30'"
                            class="w-full text-left py-2 px-3 pr-8 rounded-lg text-sm truncate transition">
                            <span x-text="conv.title || 'Conversación sin título'"></span>
                        </button>
                        <!-- Three-dots menu button -->
                        <button @click.stop="openMenu === conv.id ? openMenu = null : openMenu = conv.id"
                            class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 dark:hover:text-white opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded">
                            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                                <path
                                    d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
                            </svg>
                        </button>
                        <!-- Dropdown menu -->
                        <div x-show="openMenu === conv.id" x-cloak @click.outside="openMenu = null"
                            class="absolute right-0 top-full mt-1 z-50 bg-white dark:bg-slate-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg py-1 min-w-[120px]">
                            <button @click.stop="deleteConversation(conv.id)"
                                class="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-700/50 transition">
                                Eliminar
                            </button>
                        </div>
                    </div>
                </template>
                <p x-show="conversations.length === 0" class="text-gray-500 text-sm text-center py-4">
                    Sin conversaciones aún
                </p>
            </div>

            <!-- Footer -->
            <div class="p-3 border-t border-gray-200 dark:border-gray-700/50 text-xs text-gray-500 text-center">
                Powered by Ollama + PostgreSQL + pgvector
            </div>
        </aside>

        <!-- ═══ Main Chat Area ═══ -->
        <main class="flex-1 flex flex-col min-w-0">
            <!-- Toolbar -->
            <header
                class="h-14 bg-gray-50 dark:bg-dark-800 border-b border-gray-200 dark:border-gray-700/50 flex items-center px-4 gap-3">
                <button @click="showSidebar = !showSidebar"
                    class="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                </button>
                <h2 class="text-sm text-gray-600 dark:text-gray-300 truncate"
                    x-text="currentTitle || 'Nueva conversación'"></h2>
                <div class="ml-auto flex items-center gap-2">
                    <span x-show="lastValidation === 'valid'"
                        class="text-xs bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-400 px-2 py-1 rounded">
                        ✓ Migración válida
                    </span>
                    <span x-show="lastValidation === 'error'"
                        class="text-xs bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-400 px-2 py-1 rounded">
                        ✗ Error en migración
                    </span>
                    <!-- Theme toggle -->
                    <button @click="toggleTheme()"
                        class="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-200 dark:hover:bg-gray-700/50 transition"
                        title="Cambiar tema">
                        <!-- Sun icon (shown in dark mode) -->
                        <svg x-show="$store.theme.dark" class="w-5 h-5" fill="none" stroke="currentColor"
                            viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                        </svg>
                        <!-- Moon icon (shown in light mode) -->
                        <svg x-show="!$store.theme.dark" x-cloak class="w-5 h-5" fill="none" stroke="currentColor"
                            viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                        </svg>
                    </button>
                </div>
            </header>

            <!-- Messages -->
            <div class="flex-1 overflow-y-auto" id="messages-container">
                <!-- Welcome screen -->
                <div x-show="messages.length === 0" class="h-full flex items-center justify-center">
                    <div class="text-center max-w-lg px-4">
                        <div class="text-6xl mb-4">🏗️</div>
                        <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-2">Data Model Agent</h2>
                        <p class="text-gray-500 dark:text-gray-400 mb-6">
                            Describe tu dominio en lenguaje natural y generaré un esquema de base de datos
                            normalizado con migraciones SQL validadas.
                        </p>
                        <div class="grid grid-cols-1 gap-2 text-left">
                            <button
                                @click="sendExample('Sistema de citas médicas con doctores, pacientes, horarios disponibles y especialidades')"
                                class="p-3 bg-gray-100 dark:bg-dark-700 border border-gray-200 dark:border-gray-700/50 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:border-blue-500/50 hover:text-gray-900 dark:hover:text-white transition text-left">
                                "Sistema de citas médicas con doctores, pacientes, horarios y especialidades"
                            </button>
                            <button
                                @click="sendExample('E-commerce con productos, categorías, usuarios, carritos de compra y órdenes')"
                                class="p-3 bg-gray-100 dark:bg-dark-700 border border-gray-200 dark:border-gray-700/50 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:border-blue-500/50 hover:text-gray-900 dark:hover:text-white transition text-left">
                                "E-commerce con productos, categorías, usuarios, carritos y órdenes"
                            </button>
                            <button
                                @click="sendExample('Sistema de gestión escolar con alumnos, profesores, materias, calificaciones y grupos')"
                                class="p-3 bg-gray-100 dark:bg-dark-700 border border-gray-200 dark:border-gray-700/50 rounded-lg text-sm text-gray-600 dark:text-gray-300 hover:border-blue-500/50 hover:text-gray-900 dark:hover:text-white transition text-left">
                                "Gestión escolar con alumnos, profesores, materias, calificaciones y grupos"
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Message list -->
                <div class="max-w-4xl mx-auto py-4 px-4 space-y-4">
                    <template x-for="(msg, index) in messages" :key="index">
                        <div class="message-enter" :class="msg.role === 'user' ? 'flex justify-end' : ''">
                            <!-- User message -->
                            <div x-show="msg.role === 'user'"
                                class="max-w-[80%] bg-blue-600 text-white rounded-2xl rounded-br-md px-4 py-3">
                                <p class="text-sm whitespace-pre-wrap" x-text="msg.content"></p>
                            </div>
                            <!-- Assistant message -->
                            <div x-show="msg.role === 'assistant'" class="max-w-[90%]">
                                <div class="flex items-start gap-3">
                                    <div
                                        class="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center text-sm flex-shrink-0">
                                        🤖
                                    </div>
                                    <div class="flex-1 min-w-0">
                                        <div class="prose prose-sm dark:prose-invert max-w-none"
                                            x-html="renderMarkdown(msg.content)"></div>

                                        <!-- Schema JSON -->
                                        <div x-show="msg.schema_json" class="mt-3">
                                            <details
                                                class="bg-gray-100 dark:bg-dark-700 border border-gray-200 dark:border-gray-700/50 rounded-lg">
                                                <summary
                                                    class="px-4 py-2 text-sm text-blue-600 dark:text-blue-400 cursor-pointer hover:text-blue-500 dark:hover:text-blue-300">
                                                    Ver esquema JSON
                                                </summary>
                                                <pre
                                                    class="p-4 text-xs overflow-x-auto"><code class="language-json" x-text="JSON.stringify(msg.schema_json, null, 2)"></code></pre>
                                            </details>
                                        </div>

                                        <!-- Migration SQL -->
                                        <div x-show="msg.migration_sql" class="mt-3">
                                            <div
                                                class="bg-gray-100 dark:bg-dark-700 border border-gray-200 dark:border-gray-700/50 rounded-lg">
                                                <div
                                                    class="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700/50">
                                                    <span class="text-sm text-green-600 dark:text-green-400">📝
                                                        Migración SQL</span>
                                                    <button @click="copyToClipboard(msg.migration_sql)"
                                                        class="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white px-2 py-1 rounded bg-gray-200 dark:bg-gray-700/50">
                                                        Copiar
                                                    </button>
                                                </div>
                                                <pre
                                                    class="p-4 text-xs overflow-x-auto"><code class="language-sql" x-text="msg.migration_sql"></code></pre>
                                            </div>
                                            <!-- Validation badge -->
                                            <div class="mt-2" x-show="msg.validation_status">
                                                <span x-show="msg.validation_status === 'valid'"
                                                    class="inline-flex items-center text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-2 py-1 rounded-full">
                                                    ✓ Ejecutada exitosamente contra BD de prueba
                                                </span>
                                                <span x-show="msg.validation_status === 'error'"
                                                    class="inline-flex items-center text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 px-2 py-1 rounded-full">
                                                    ✗ Error: <span x-text="msg.validation_error" class="ml-1"></span>
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </template>

                    <!-- Typing indicator -->
                    <div x-show="isLoading" class="flex items-start gap-3 message-enter">
                        <div class="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center text-sm">🤖
                        </div>
                        <div class="bg-gray-100 dark:bg-dark-700 rounded-2xl rounded-bl-md px-4 py-3">
                            <div class="flex gap-1">
                                <div class="w-2 h-2 bg-gray-400 rounded-full typing-dot"></div>
                                <div class="w-2 h-2 bg-gray-400 rounded-full typing-dot"></div>
                                <div class="w-2 h-2 bg-gray-400 rounded-full typing-dot"></div>
                            </div>
                            <p class="text-xs text-gray-500 mt-1" x-text="loadingText"></p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Input area -->
            <div class="border-t border-gray-200 dark:border-gray-700/50 bg-gray-50 dark:bg-dark-800 p-4">
                <form @submit.prevent="sendMessage()" class="max-w-4xl mx-auto flex gap-3">
                    <input type="text" x-model="input" :disabled="isLoading"
                        placeholder="Describe tu dominio o pide cambios al esquema..."
                        class="flex-1 bg-white dark:bg-dark-700 border border-gray-300 dark:border-gray-600/50 rounded-xl px-4 py-3 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                        autocomplete="off">
                    <button type="submit" :disabled="isLoading || !input.trim()"
                        class="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 dark:disabled:bg-gray-700 disabled:text-gray-500 text-white px-5 py-3 rounded-xl text-sm font-medium transition">
                        <span x-show="!isLoading">Enviar</span>
                        <span x-show="isLoading">...</span>
                    </button>
                </form>
                <p class="text-center text-xs text-gray-400 dark:text-gray-600 mt-2">
                    El agente genera esquemas PostgreSQL y valida migraciones en tiempo real
                </p>
            </div>
        </main>
    </div>

    <script>
        function chatApp() {
            return {
                messages: [],
                input: '',
                isLoading: false,
                loadingText: 'Analizando dominio y generando esquema...',
                conversationId: null,
                conversations: [],
                showSidebar: true,
                currentTitle: '',
                lastValidation: null,
                openMenu: null,

                async init() {
                    await this.loadConversations();
                    this.applyHljsTheme();
                },

                toggleTheme() {
                    Alpine.store('theme').toggle();
                    this.applyHljsTheme();
                },

                applyHljsTheme() {
                    const isDark = Alpine.store('theme').dark;
                    const themeLink = document.getElementById('hljs-theme');
                    if (isDark) {
                        themeLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css';
                    } else {
                        themeLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
                    }
                },

                async deleteConversation(id) {
                    this.openMenu = null;
                    try {
                        await fetch(`/api/conversations/${id}`, {
                            method: 'DELETE',
                            headers: {
                                'X-CSRF-TOKEN': document.querySelector('meta[name="csrf-token"]').content,
                                'Accept': 'application/json',
                            },
                        });

                        // If the deleted conversation was active, reset
                        if (this.conversationId === id) {
                            this.newConversation();
                        }

                        await this.loadConversations();
                    } catch (e) {
                        console.error('Error eliminando conversación:', e);
                    }
                },

                async sendMessage() {
                    const message = this.input.trim();
                    if (!message || this.isLoading) return;

                    this.input = '';
                    this.messages.push({ role: 'user', content: message });
                    this.isLoading = true;
                    this.loadingText = 'Analizando dominio y consultando buenas prácticas...';
                    this.scrollToBottom();

                    setTimeout(() => {
                        this.loadingText = 'Generando esquema y validando migraciones...';
                    }, 3000);

                    try {
                        const response = await fetch('/api/chat', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRF-TOKEN': document.querySelector('meta[name="csrf-token"]').content,
                                'Accept': 'application/json',
                            },
                            body: JSON.stringify({
                                message: message,
                                conversation_id: this.conversationId,
                            }),
                        });

                        const data = await response.json();

                        this.conversationId = data.conversation_id || this.conversationId;
                        if (!this.currentTitle) {
                            this.currentTitle = message.substring(0, 60);
                        }

                        this.messages.push({
                            role: 'assistant',
                            content: data.message,
                            schema_json: data.schema_json,
                            migration_sql: data.migration_sql,
                            validation_status: data.validation_status,
                            validation_error: data.validation_error,
                        });

                        this.lastValidation = data.validation_status;
                        await this.loadConversations();

                    } catch (error) {
                        this.messages.push({
                            role: 'assistant',
                            content: `Error de conexión: ${error.message}. Verifica que el orquestador esté corriendo.`,
                        });
                    }

                    this.isLoading = false;
                    this.scrollToBottom();
                    this.$nextTick(() => hljs.highlightAll());
                },

                sendExample(text) {
                    this.input = text;
                    this.sendMessage();
                },

                newConversation() {
                    this.messages = [];
                    this.conversationId = null;
                    this.currentTitle = '';
                    this.lastValidation = null;
                },

                async loadConversation(id) {
                    try {
                        const response = await fetch(`/api/conversations/${id}/messages`);
                        const data = await response.json();

                        this.conversationId = id;
                        this.messages = data.map(msg => ({
                            role: msg.role,
                            content: msg.content,
                            schema_json: msg.metadata?.schema_json,
                            migration_sql: msg.metadata?.migration_sql,
                            validation_status: msg.metadata?.validation_status,
                        }));

                        const conv = this.conversations.find(c => c.id === id);
                        this.currentTitle = conv?.title || '';

                        this.$nextTick(() => hljs.highlightAll());
                    } catch (e) {
                        console.error('Error cargando conversación:', e);
                    }
                },

                async loadConversations() {
                    try {
                        const response = await fetch('/api/conversations');
                        this.conversations = await response.json();
                    } catch (e) {
                        console.error('Error cargando conversaciones:', e);
                    }
                },

                renderMarkdown(text) {
                    if (!text) return '';
                    // Basic markdown rendering
                    let html = text
                        // Headers
                        .replace(/^### (.+)$/gm, '<h3 class="text-lg font-semibold text-gray-900 dark:text-white mt-3 mb-1">$1</h3>')
                        .replace(/^## (.+)$/gm, '<h2 class="text-xl font-bold text-gray-900 dark:text-white mt-4 mb-2">$1</h2>')
                        // Bold
                        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-gray-900 dark:text-white">$1</strong>')
                        // Italic
                        .replace(/\*(.+?)\*/g, '<em>$1</em>')
                        // Inline code
                        .replace(/`([^`]+)`/g, '<code class="bg-gray-200 dark:bg-gray-700/50 px-1.5 py-0.5 rounded text-blue-600 dark:text-blue-300 text-xs">$1</code>')
                        // Lists
                        .replace(/^- (.+)$/gm, '<li class="ml-4 text-gray-700 dark:text-gray-300">• $1</li>')
                        .replace(/^\d+\. (.+)$/gm, '<li class="ml-4 text-gray-700 dark:text-gray-300">$1</li>')
                        // Paragraphs
                        .replace(/\n\n/g, '</p><p class="text-gray-700 dark:text-gray-300 text-sm mb-2">')
                        .replace(/\n/g, '<br>');

                    return `<p class="text-gray-700 dark:text-gray-300 text-sm mb-2">${html}</p>`;
                },

                copyToClipboard(text) {
                    navigator.clipboard.writeText(text).then(() => {
                        // Brief visual feedback could be added here
                    });
                },

                scrollToBottom() {
                    this.$nextTick(() => {
                        const container = document.getElementById('messages-container');
                        container.scrollTop = container.scrollHeight;
                    });
                }
            };
        }
    </script>
</body>

</html>