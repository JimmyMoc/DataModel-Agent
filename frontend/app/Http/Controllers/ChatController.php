<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;

class ChatController extends Controller
{
    private string $orchestratorUrl;

    public function __construct()
    {
        $this->orchestratorUrl = env('ORCHESTRATOR_URL', 'http://orchestrator:8000');
    }

    /**
     * Página principal del chat.
     */
    public function index()
    {
        return view('chat.index');
    }

    /**
     * Enviar mensaje al orquestador.
     */
    public function sendMessage(Request $request)
    {
        $request->validate([
            'message' => 'required|string|max:2000',
            'conversation_id' => 'nullable|string',
        ]);

        try {
            $response = Http::timeout(300)->post("{$this->orchestratorUrl}/api/chat/", [
                'message' => $request->input('message'),
                'conversation_id' => $request->input('conversation_id'),
            ]);

            if ($response->successful()) {
                return response()->json($response->json());
            }

            return response()->json([
                'message' => 'Error del orquestador: ' . $response->body(),
                'conversation_id' => $request->input('conversation_id'),
            ], 500);

        } catch (\Exception $e) {
            return response()->json([
                'message' => 'No se pudo conectar con el agente: ' . $e->getMessage(),
                'conversation_id' => $request->input('conversation_id'),
            ], 503);
        }
    }

    /**
     * Obtener historial de una conversación.
     */
    public function getMessages(string $conversationId)
    {
        try {
            $response = Http::timeout(10)->get(
                "{$this->orchestratorUrl}/api/chat/conversations/{$conversationId}/messages"
            );

            if ($response->successful()) {
                return response()->json($response->json());
            }

            return response()->json([], 404);

        } catch (\Exception $e) {
            return response()->json([], 503);
        }
    }

    /**
     * Listar conversaciones.
     */
    public function listConversations()
    {
        try {
            $response = Http::timeout(10)->get(
                "{$this->orchestratorUrl}/api/chat/conversations"
            );

            if ($response->successful()) {
                return response()->json($response->json());
            }

            return response()->json([]);

        } catch (\Exception $e) {
            return response()->json([]);
        }
    }

    /**
     * Eliminar una conversación.
     */
    public function deleteConversation(string $conversationId)
    {
        try {
            $response = Http::timeout(10)->delete(
                "{$this->orchestratorUrl}/api/chat/conversations/{$conversationId}"
            );

            if ($response->successful()) {
                return response()->json(['success' => true]);
            }

            return response()->json(['success' => false], $response->status());

        } catch (\Exception $e) {
            return response()->json(['success' => false], 503);
        }
    }
}
