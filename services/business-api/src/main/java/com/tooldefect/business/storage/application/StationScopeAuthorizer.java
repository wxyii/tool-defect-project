package com.tooldefect.business.storage.application;

import java.util.UUID;

public interface StationScopeAuthorizer {
    boolean mayWrite(UUID actorStationId, UUID objectStationId);

    boolean mayRead(String actorId, UUID imageId, String purpose);
}
