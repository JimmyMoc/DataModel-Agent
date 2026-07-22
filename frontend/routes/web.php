<?php

use App\Http\Controllers\ChatController;
use Illuminate\Support\Facades\Route;

// Página principal - Chat
Route::get('/', [ChatController::class, 'index'])->name('chat');

// API endpoints para el frontend
Route::post('/api/chat', [ChatController::class, 'sendMessage'])->name('chat.send');
Route::get('/api/conversations', [ChatController::class, 'listConversations'])->name('conversations.list');
Route::get('/api/conversations/{conversationId}/messages', [ChatController::class, 'getMessages'])->name('conversations.messages');
Route::delete('/api/conversations/{conversationId}', [ChatController::class, 'deleteConversation'])->name('conversations.delete');
