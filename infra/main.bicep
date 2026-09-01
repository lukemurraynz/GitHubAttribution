// Azure Container Apps deployment for the GitHub Copilot cost collector.
//
// Design (permanent decisions, see docs/SETUP-REAL-ORG.md and the azd/ACA skills):
//   - Host: Standard ACA, Workload Profiles managed environment (Consumption plan, scale-to-zero).
//   - Ingress: EXTERNAL, HTTPS-only. The collector is reached by Copilot hooks on
//     developers' machines over the internet, so it cannot be a VNet-internal endpoint.
//   - Storage: SQLite DB persisted on an Azure Files share mounted read-write (survives
//     scale-to-zero and multi-replica restarts). Not on the ephemeral container FS.
//   - Identity: a user-assigned managed identity is used for ACR pull, Key Vault secret
//     access, and the file share. No ingress key is ever stored in plaintext env vars.
//   - Secrets: COPILOT_COST_INGEST_KEY comes from a Key Vault secret referenced by the
//     Container App and resolved via the managed identity at runtime.
//   - Image: deployed with a deterministic, non-:latest tag supplied at deploy time.

param name string
param location string = resourceGroup().location
param environmentName string = ''
param managedIdentityName string = ''
param keyVaultName string = ''
param acrName string = ''
param storageAccountName string = ''
param fileShareName string = ''
param tags object = {}

// Internationalized / non-KV-safe secret name placeholder kept out; the vault
// secret is created by the "GITHUB_COPILOT_INGEST_KEY" postdeploy step.
// The deterministic container image is supplied by azd at deploy time.
param secretName string = 'copilot-cost-ingest-key'

// Deterministic image tag passed by azd at deploy time (e.g. commit SHA). Never ':latest'.
@description('Fully qualified container image: registry/repo@sha256 or registry/repo:tag')
param containerImage string

// Build a stable, lowercased, legal Azure resource name.
func legalName(base string) string => toLower(replace(replace(take(base, 16), '-', ''), '_', ''))

// ---------------------------------------------------------------- names
var envName = !empty(environmentName) ? environmentName : 'ca-${name}'
var miName = !empty(managedIdentityName) ? managedIdentityName : 'uami-${name}'
var kvName = !empty(keyVaultName) ? keyVaultName : 'kv-${legalName(name)}${substring(uniqueString(resourceGroup().id, name), 0, 6)}'
var acrName_ = !empty(acrName) ? acrName : 'acr${legalName(name)}${substring(uniqueString(resourceGroup().id, name), 0, 6)}'
var stgName = !empty(storageAccountName) ? storageAccountName : 'st${legalName(name)}${substring(uniqueString(resourceGroup().id, name), 0, 6)}'
var shareName = !empty(fileShareName) ? fileShareName : 'copilotcost'

// ---------------------------------------------------------------- managed identity
resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: miName
  location: location
  tags: tags
}

// ---------------------------------------------------------------- container registry
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName_
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
  tags: tags
}

// AcrPull for the managed identity (private pulls only; no admin user).
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, 'acrpull')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed8-4680-a7ca-43fe172d538d') // AcrPull
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- key vault
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableSoftDelete: true
    enablePurgeProtection: true
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 90
    // No network restrictions by default so the managed identity + role assignment work;
    // tighten with networkAcls in a hardened deployment.
  }
  tags: tags
}

// Key Vault Secrets User (data-plane) for the managed identity.
resource kvSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, 'kvsecretsuser')
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- storage (Azure Files for SQLite)
resource stg 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: stgName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    networkAcls: { defaultAction: 'Allow' }
  }
  tags: tags
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  name: '${stgName}/default/${shareName}'
}

// ---------------------------------------------------------------- managed env (Workload Profiles / Consumption)
resource env 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: envName
  location: location
  properties: {
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
  tags: tags
}

// ---------------------------------------------------------------- container app
resource app 'Microsoft.App/containerApps@2025-07-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${mi.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false // HTTPS-only
      }
      secrets: [
        {
          name: secretName
          keyVaultUrl: '${kv.properties.vaultUri}secrets/${secretName}'
          identity: mi.id
        }
      ]
      registries: [
        {
          server: acr.properties.loginServer
          identity: mi.id
        }
      ]
    }
    template: {
      containers: [
        {
          image: containerImage
          name: 'collector'
          env: [
            { name: 'COPILOT_COST_HOST', value: '0.0.0.0' }
            { name: 'COPILOT_COST_PORT', value: '8080' }
            { name: 'COPILOT_COST_DB', value: '/data/copilot-cost.sqlite3' }
            { name: 'COPILOT_COST_INGEST_KEY', secretRef: secretName }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          volumeMounts: [
            { volumeName: 'data', mountPath: '/data' }
          ]
        }
      ]
      scale: {
        minReplicas: 0 // scale-to-zero; paid Copilot data volume is low-touch event ingest
        maxReplicas: 3
      }
      volumes: [
        {
          name: 'data'
          storageType: 'AzureFile'
          storageName: share.name
        }
      ]
    }
  }
  tags: tags
}

// ---------------------------------------------------------------- outputs
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output managedEnvironmentName string = env.name
output resourceGroupName string = resourceGroup().name
output managedIdentityId string = mi.id
output keyVaultName string = kv.name
output acrName string = acr.name
output storageAccountName string = stg.name
output fileShareName string = shareName
