
with open(r'C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend\main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Add comprehensive logging to reveal_lead call
content = content.replace(
    '''        try:
            result = await db_service.reveal_lead(user_id, lead_id, key, minutes=minutes)
        except Exception as e:
            logger.error(f"Erro ao revelar lead {lead_id}: {e}")
            raise HTTPException(status_code=500, detail="Erro ao processar reserva")''',
    '''        logger.info(f"[RESERVE] Calling reveal_lead user_id={user_id} lead_id={lead_id} key={key} minutes={minutes}")
        try:
            result = await db_service.reveal_lead(user_id, lead_id, key, minutes=minutes)
            logger.info(f"[RESERVE] reveal_lead result: {result}")
        except Exception as e:
            logger.exception(f"[RESERVE] EXCEPTION in reveal_lead user_id={user_id} lead_id={lead_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao processar reserva: {e}")''')

# Fix 2: Add comprehensive logging to enrichment section
content = content.replace(
    '''        lead = result.get("lead") or {}

        # ENRIQUECIMENTO ON-DEMAND: se dados do dono faltam, busca nas APIs externas
        try:
                owner_name = lead.get("owner_name")
                owner_phone = lead.get("owner_phone")
                owner_email = lead.get("owner_email")
                mailing_address = lead.get("mailing_address")

                needs_enrichment = not owner_name or not owner_phone or not mailing_address

                enrichment_failed = False

                if needs_enrichment:
                    # Enriquecimento de nome + mailing address (Socrata/CKAN)
                    enrich_result = await owner_enrichment.enrich(lead.get("address", ""), lead.get("city", ""))
                    if enrich_result:
                        if not owner_name and enrich_result.get("owner_name"):
                            owner_name = enrich_result["owner_name"]
                            await db_service.update_owner(lead_id, owner_name)
                        if not mailing_address and enrich_result.get("mailing_address"):
                            mailing_address = enrich_result["mailing_address"]
                            await db_service.update_mailing_address(lead_id, mailing_address)
                else:
                    enrichment_failed = True

                # Busca de telefone (Searchbug em prod, mock em dev)
                if not owner_phone:
                    phone_result = await searchbug_service.lookup_phone(lead.get("address", ""), lead.get("city", ""), lead.get("state", ""))
                    if phone_result.success:
                        owner_phone = phone_result.phone
                        await db_service.update_owner_phone(lead_id, owner_phone)
                    else:
                        enrichment_failed = True

                # Recarrega lead com dados enriquecidos
                enriched_lead = await db_service.get_lead_by_id(lead_id)
                if enriched_lead:
                    lead = dict(enriched_lead)

            except Exception as e:
                logger.warning(f"Enriquecimento on-demand falhou para lead {lead_id}: {e}")
                enrichment_failed = True

            # REGRA A: Se enriquecimento falhou ou dados vazios, não debita a cota diária
            if enrichment_failed or not lead.get("owner_name") or not lead.get("owner_phone"):
                logger.info(f"Regra A aplicada: estorno de cota por dados vazios/falha no lead {lead_id}")
                refund_result = await db_service.process_refund(user_id, lead_id, reason="enrichment_failed")
                if not refund_result.get("success"):
                    logger.warning(f"Falha ao processar estorno Regra A: {refund_result.get('reason')}")''',
    '''        lead = result.get("lead") or {}
            logger.info(f"[RESERVE] Lead after reveal: lead_id={lead_id} status={lead.get('lead_status')}")

            # ENRIQUECIMENTO ON-DEMAND: se dados do dono faltam, busca nas APIs externas
            try:
                owner_name = lead.get("owner_name")
                owner_phone = lead.get("owner_phone")
                owner_email = lead.get("owner_email")
                mailing_address = lead.get("mailing_address")

                needs_enrichment = not owner_name or not owner_phone or not mailing_address
                logger.info(f"[RESERVE] Enrichment check: needs_enrichment={needs_enrichment} owner_name={bool(owner_name)} owner_phone={bool(owner_phone)} mailing_address={bool(mailing_address)}")

                enrichment_failed = False

                if needs_enrichment:
                    # Enriquecimento de nome + mailing address (Socrata/CKAN)
                    logger.info(f"[RESERVE] Calling owner_enrichment.enrich for lead_id={lead_id}")
                    enrich_result = await owner_enrichment.enrich(lead.get("address", ""), lead.get("city", ""))
                    logger.info(f"[RESERVE] owner_enrichment result: {enrich_result}")
                    if enrich_result:
                        if not owner_name and enrich_result.get("owner_name"):
                            owner_name = enrich_result["owner_name"]
                            await db_service.update_owner(lead_id, owner_name)
                            logger.info(f"[RESERVE] Updated owner_name for lead_id={lead_id}")
                        if not mailing_address and enrich_result.get("mailing_address"):
                            mailing_address = enrich_result["mailing_address"]
                            await db_service.update_mailing_address(lead_id, mailing_address)
                            logger.info(f"[RESERVE] Updated mailing_address for lead_id={lead_id}")
                    else:
                        enrichment_failed = True
                        logger.warning(f"[RESERVE] owner_enrichment returned None/empty for lead_id={lead_id}")

                    # Busca de telefone (Searchbug em prod, mock em dev)
                    if not owner_phone:
                        logger.info(f"[RESERVE] Calling searchbug_service.lookup_phone for lead_id={lead_id}")
                        phone_result = await searchbug_service.lookup_phone(lead.get("address", ""), lead.get("city", ""), lead.get("state", ""))
                        logger.info(f"[RESERVE] searchbug_service result: success={phone_result.success} phone={phone_result.phone} error={phone_result.error}")
                        if phone_result.success:
                            owner_phone = phone_result.phone
                            await db_service.update_owner_phone(lead_id, owner_phone)
                            logger.info(f"[RESERVE] Updated owner_phone for lead_id={lead_id}")
                        else:
                            enrichment_failed = True
                            logger.warning(f"[RESERVE] Searchbug failed: {phone_result.error}")

                    # Recarrega lead com dados enriquecidos
                    enriched_lead = await db_service.get_lead_by_id(lead_id)
                    if enriched_lead:
                        lead = dict(enriched_lead)
                        logger.info(f"[RESERVE] Reloaded enriched lead: lead_id={lead_id}")

            except Exception as e:
                logger.exception(f"[RESERVE] EXCEPTION in enrichment for lead_id={lead_id}: {e}")
                enrichment_failed = True

            # REGRA A: Se enriquecimento falhou ou dados vazios, não debita a cota diária
            if enrichment_failed or not lead.get("owner_name") or not lead.get("owner_phone"):
                logger.info(f"[RESERVE] Regra A aplicada: estorno de cota por dados vazios/falha no lead {lead_id} enrichment_failed={enrichment_failed} owner_name={bool(lead.get('owner_name'))} owner_phone={bool(lead.get('owner_phone'))}")
                refund_result = await db_service.process_refund(user_id, lead_id, reason="enrichment_failed")
                logger.info(f"[RESERVE] Refund result: {refund_result}")
                if not refund_result.get("success"):
                    logger.warning(f"[RESERVE] Falha ao processar estorno Regra A: {refund_result.get('reason')}")''')

with open(r'C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend\main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Applied comprehensive logging to reserve_lead endpoint')
