<script setup lang="ts">
import { provide } from 'vue'
import App from '../App.vue'
import { apiKey, type Schema } from '../api'
import type { TravelClient } from '../../../../packages/api-schema/client'
const props=defineProps<{api:TravelClient;user:Schema<'AuthUser'>;authEnabled:boolean}>()
defineEmits<{logout:[]}>()
provide(apiKey,props.api)
</script>

<template><App :user="user" :auth-enabled="authEnabled" @logout="$emit('logout')"/></template>
