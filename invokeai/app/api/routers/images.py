import io
import asyncio
from operator import is_
from re import L
import traceback
from typing import Optional, List
import time


from fastapi import Body, HTTPException, Path, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from invokeai.app.invocations.baseinvocation import MetadataField, MetadataFieldValidator
from invokeai.app.services.image_records.image_records_common import ImageCategory, ImageRecordChanges, ResourceOrigin
from invokeai.app.services.images.images_common import ImageDTO, ImageUrlsDTO, ImageUploadData
from invokeai.app.services.shared.pagination import OffsetPaginatedResults
from invokeai.app.services.workflow_records.workflow_records_common import WorkflowWithoutID, WorkflowWithoutIDValidator

from ..dependencies import ApiDependencies

images_router = APIRouter(prefix="/v1/images", tags=["images"])


# images are immutable; set a high max-age
IMAGE_MAX_AGE = 31536000

############################################################################################################
############################    ERYX CODE   ############################################################
############################################################################################################

@images_router.post(
    "/upload_multiple",
    operation_id="upload_multiple_images",
    responses={
        201: {"description": "The images were uploaded successfully"},
        415: {"description": "Images upload failed"},
    },
    status_code=201,
    response_model=List[ImageDTO],
)
async def upload_images(
    files: List[UploadFile],
    request: Request,
    response: Response,
    image_category: ImageCategory = Query(description="The category of the images"),
    is_intermediate: bool = Query(description="Whether this is an intermediate images"),
    board_id: Optional[str] = Query(default=None, description="The board to add this images to, if any"),
    session_id: Optional[str] = Query(default=None, description="The session ID associated with this upload, if any"),
    crop_visible: Optional[bool] = Query(default=False, description="Whether to crop the images"),
) -> List[ImageDTO]:
    """Uploads multiple images"""
    upload_data_list = []

    print("-------------images.py-------------------")
    print(is_intermediate)
    print(image_category)
    print("-----------------------------------------")

    # my added loop to handle multiple files
    for file in files:
        if not file.content_type or not file.content_type.startswith("image"):
            raise HTTPException(status_code=415, detail="Not an image")

        metadata = None
        workflow = None

        contents = await file.read()
        try:
            pil_image = Image.open(io.BytesIO(contents))
            if crop_visible:
                bbox = pil_image.getbbox()
                pil_image = pil_image.crop(bbox)
        except Exception:
            ApiDependencies.invoker.services.logger.error(traceback.format_exc())
            raise HTTPException(status_code=415, detail="Failed to read image")

        # attempt to parse metadata from image
        metadata_raw = pil_image.info.get("invokeai_metadata", None)
        if metadata_raw:
            try:
                metadata = MetadataFieldValidator.validate_json(metadata_raw)
            except ValidationError:
                ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
                pass

        # attempt to parse workflow from image
        workflow_raw = pil_image.info.get("invokeai_workflow", None)
        if workflow_raw is not None:
            try:
                workflow = WorkflowWithoutIDValidator.validate_json(workflow_raw)
            except ValidationError:
                ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
                pass
        # constructed an ImageUploadData object for each file
        upload_data = ImageUploadData(
            image=pil_image,
            image_origin=ResourceOrigin.EXTERNAL,
            image_category=image_category,
            session_id=session_id,
            board_id=board_id,
            metadata=metadata,
            workflow=workflow,
            is_intermediate=is_intermediate
        )
        upload_data_list.append(upload_data)

    try:
        image_dtos = await ApiDependencies.invoker.services.images.create_eryx(upload_data_list)
        
        response.status_code = 201
        response.headers["Location"] = image_dtos[0].image_url if image_dtos else ""
        
        # Return the list of ImageDTOs after processing all files
        return image_dtos
    
    except Exception:
        ApiDependencies.invoker.services.logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to create image")

############################################################################################################
############################################################################################################
############################################################################################################


############################################################################################################
############################    ORIGINAL CODE   ############################################################
############################################################################################################
@images_router.post(
    "/upload",
    operation_id="upload_image",
    responses={
        201: {"description": "The image was uploaded successfully"},
        415: {"description": "Image upload failed"},
    },
    status_code=201,
    response_model=ImageDTO,
)
async def upload_image(
    file: UploadFile,
    request: Request,
    response: Response,
    image_category: ImageCategory = Query(description="The category of the image"),
    is_intermediate: bool = Query(description="Whether this is an intermediate image"),
    board_id: Optional[str] = Query(default=None, description="The board to add this image to, if any"),
    session_id: Optional[str] = Query(default=None, description="The session ID associated with this upload, if any"),
    crop_visible: Optional[bool] = Query(default=False, description="Whether to crop the image"),
) -> ImageDTO:
    """Uploads an image"""
    print("-------------images.py-------------------")
    print("/upload route for single file upload")
    print("-----------------------------------------")
    print(file.filename, file.content_type)
    if not file.content_type or not file.content_type.startswith("image"):
        raise HTTPException(status_code=415, detail="Not an image")

    metadata = None
    workflow = None

    contents = await file.read()
    try:
        pil_image = Image.open(io.BytesIO(contents))
        if crop_visible:
            bbox = pil_image.getbbox()
            pil_image = pil_image.crop(bbox)
    except Exception:
        ApiDependencies.invoker.services.logger.error(traceback.format_exc())
        raise HTTPException(status_code=415, detail="Failed to read image")

    # TOD0O: retain non-invokeai metadata on upload?
    # attempt to parse metadata from image
    metadata_raw = pil_image.info.get("invokeai_metadata", None)
    if metadata_raw:
        try:
            metadata = MetadataFieldValidator.validate_json(metadata_raw)
        except ValidationError:
            ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
            pass

    # attempt to parse workflow from image
    workflow_raw = pil_image.info.get("invokeai_workflow", None)
    if workflow_raw is not None:
        try:
            workflow = WorkflowWithoutIDValidator.validate_json(workflow_raw)
        except ValidationError:
            ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
            pass

    try:
        image_dto = ApiDependencies.invoker.services.images.create(
            image=pil_image,
            image_origin=ResourceOrigin.EXTERNAL,
            image_category=image_category,
            session_id=session_id,
            board_id=board_id,
            metadata=metadata,
            workflow=workflow,
            is_intermediate=is_intermediate,
        )

        response.status_code = 201
        response.headers["Location"] = image_dto.image_url

        return image_dto
    except Exception:
        ApiDependencies.invoker.services.logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to create image")
############################################################################################################
############################################################################################################
############################################################################################################

# # My helper function to process the images in batches instead of one by one
# async def process_file(file, image_category, is_intermediate, board_id, session_id, crop_visible):
#     print("-------------images.py-------------------")
#     print(file.filename, file.content_type)
#     print("-----------------------------------------")

#     if not file.content_type or not file.content_type.startswith("image"):
#         raise HTTPException(status_code=415, detail="Not an image")
    
#     metadata = None
#     workflow = None

#     # Read file content
#     contents = await file.read()

#     # Process with PIL
#     try:
#         pil_image = Image.open(io.BytesIO(contents))
#         if crop_visible:
#             bbox = pil_image.getbbox()
#             pil_image = pil_image.crop(bbox)
#     except Exception:
#         ApiDependencies.invoker.services.logger.error(traceback.format_exc())
#         raise HTTPException(status_code=415, detail="Failed to read image")
    
    

#     ## TOD0O: retain non-invokeai metadata on upload?
#     # attempt to parse metadata from image
#     metadata_raw = pil_image.info.get("invokeai_metadata", None)
#     if metadata_raw:
#         try:
#             metadata = MetadataFieldValidator.validate_json(metadata_raw)
#         except ValidationError:
#             ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
#             pass

#     # attempt to parse workflow from image
#     workflow_raw = pil_image.info.get("invokeai_workflow", None)
#     if workflow_raw is not None:
#         try:
#             workflow = WorkflowWithoutIDValidator.validate_json(workflow_raw)
#         except ValidationError:
#             ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
#             pass

#     # Image creation process
#     create_start = time.perf_counter()
#     try:
#         image_dto = ApiDependencies.invoker.services.images.create(
#             image=pil_image,
#             image_origin=ResourceOrigin.EXTERNAL,
#             image_category=image_category,
#             session_id=session_id,
#             board_id=board_id,
#             metadata=None,  # Replace with actual metadata if available
#             workflow=None,  # Replace with actual workflow if available
#             is_intermediate=is_intermediate,
#         )
#     except Exception:
#         ApiDependencies.invoker.services.logger.error(traceback.format_exc())
#         raise HTTPException(status_code=500, detail="Failed to create image")
#     create_duration = time.perf_counter() - create_start
#     print(f"Time for image creation: {create_duration:.6f} seconds")

#     return image_dto


# # Function to process images concurrently in batches
# async def process_files_concurrently(files, image_category, is_intermediate, board_id, session_id, crop_visible):
#     # Create a list of tasks for each file to be processed
#     tasks = [process_file(file, image_category, is_intermediate, board_id, session_id, crop_visible) for file in files]
#     # Use asyncio.gather to process files concurrently
#     return await asyncio.gather(*tasks)


# @images_router.post(
#     "/upload",
#     operation_id="upload_image",
#     responses={
#         201: {"description": "The images were uploaded successfully"},
#         415: {"description": "Image upload failed"},
#     },
#     status_code=201,
#     response_model=List[ImageDTO],
# )
# async def upload_image(
#     files: List[UploadFile],
#     request: Request,
#     response: Response,
#     image_category: ImageCategory = Query(description="The category of the image"),
#     is_intermediate: bool = Query(description="Whether this is an intermediate image"),
#     board_id: Optional[str] = Query(default=None, description="The board to add this image to, if any"),
#     session_id: Optional[str] = Query(default=None, description="The session ID associated with this upload, if any"),
#     crop_visible: Optional[bool] = Query(default=False, description="Whether to crop the image"),
# ) -> List[ImageDTO]:
#     """Uploads an image"""
#     image_dtos = await process_files_concurrently(files, image_category, is_intermediate, board_id, session_id, crop_visible)
#     return image_dtos
    # image_dtos = []
    # # my added loop to handle multiple files
    # for file in files:
    #     print("-------------images.py-------------------")
    #     print(file.filename, file.content_type)
    #     print("-----------------------------------------")


    #     if not file.content_type or not file.content_type.startswith("image"):
    #         raise HTTPException(status_code=415, detail="Not an image")

    #     metadata = None
    #     workflow = None

    #     contents = await file.read()
    #     try:
    #         pil_image = Image.open(io.BytesIO(contents))
    #         if crop_visible:
    #             bbox = pil_image.getbbox()
    #             pil_image = pil_image.crop(bbox)
    #     except Exception:
    #         ApiDependencies.invoker.services.logger.error(traceback.format_exc())
    #         raise HTTPException(status_code=415, detail="Failed to read image")

    #     # TOD0O: retain non-invokeai metadata on upload?
    #     # attempt to parse metadata from image
    #     metadata_raw = pil_image.info.get("invokeai_metadata", None)
    #     if metadata_raw:
    #         try:
    #             metadata = MetadataFieldValidator.validate_json(metadata_raw)
    #         except ValidationError:
    #             ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
    #             pass

    #     # attempt to parse workflow from image
    #     workflow_raw = pil_image.info.get("invokeai_workflow", None)
    #     if workflow_raw is not None:
    #         try:
    #             workflow = WorkflowWithoutIDValidator.validate_json(workflow_raw)
    #         except ValidationError:
    #             ApiDependencies.invoker.services.logger.warn("Failed to parse metadata for uploaded image")
    #             pass

    #     try:
    #         image_dto = ApiDependencies.invoker.services.images.create(
    #             image=pil_image,
    #             image_origin=ResourceOrigin.EXTERNAL,
    #             image_category=image_category,
    #             session_id=session_id,
    #             board_id=board_id,
    #             metadata=metadata,
    #             workflow=workflow,
    #             is_intermediate=is_intermediate,
    #         )
    #         # added by me: 
    #         image_dtos.append(image_dto)

    #         response.status_code = 201
    #         response.headers["Location"] = image_dto.image_url

    #         # return image_dto
    #     except Exception as e:
    #         ApiDependencies.invoker.services.logger.error(traceback.format_exc())
    #         raise HTTPException(status_code=500, detail=f"Failed to create image: {str(e)}")
            
    # return image_dtos  # Return the list of ImageDTOs after processing all files


# @images_router.post(
#     "/upload",
#     operation_id="upload_image",
#     responses={
#         201: {"description": "The images were uploaded successfully"},
#         415: {"description": "Image upload failed"},
#     },
#     status_code=201,
#     response_model=List[ImageDTO],
# )
# @images_router.post(
#     "/upload",
#     operation_id="upload_image",
#     responses={
#         201: {"description": "The images were uploaded successfully"},
#         415: {"description": "Image upload failed"},
#     },
#     status_code=201,
#     response_model=List[ImageDTO],
# )
# async def upload_image(
#     files: List[UploadFile],
#     request: Request,
#     response: Response,
#     image_category: ImageCategory = Query(description="The category of the image"),
#     is_intermediate: bool = Query(description="Whether this is an intermediate image"),
#     board_id: Optional[str] = Query(default=None, description="The board to add this image to, if any"),
#     session_id: Optional[str] = Query(default=None, description="The session ID associated with this upload, if any"),
#     crop_visible: Optional[bool] = Query(default=False, description="Whether to crop the image"),
# ) -> List[ImageDTO]:
#     """Uploads an image"""

#     print("-------------images.py-------------------")
#     print(files)
#     print("-----------------------------------------")

#     # Prepare data for batch processing
#     images = []
#     node_ids = []
#     session_ids = []
#     board_ids = []
#     metadatas = []
#     workflows = []

#     for file in files:
#         # Process the file and populate the lists
#         contents = await file.read()
#         try:
#             pil_image = Image.open(io.BytesIO(contents))
#             if crop_visible:
#                 bbox = pil_image.getbbox()
#                 pil_image = pil_image.crop(bbox)
#         except Exception:
#             ApiDependencies.invoker.services.logger.error(traceback.format_exc())
#             raise HTTPException(status_code=415, detail="Failed to read image")

#         images.append(pil_image)
#         node_ids.append(None)  # Update if node_id is applicable
#         session_ids.append(session_id)
#         board_ids.append(board_id)
#         metadatas.append(None)  # Update with actual metadata if available
#         workflows.append(None)  # Update with actual workflow if available

#     # Create images in batch
#     image_dtos = ApiDependencies.invoker.services.images.create_many(
#         images=images,
#         image_origin=ResourceOrigin.EXTERNAL,
#         image_category=image_category,
#         node_ids=node_ids,
#         session_ids=session_ids,
#         board_ids=board_ids,
#         is_intermediate=is_intermediate,
#         metadatas=metadatas,
#         workflows=workflows
#     )

#     print("-------------images.py-------------------")
#     print(image_dtos)
#     print("-----------------------------------------")
    
#     return image_dtos




@images_router.delete("/i/{image_name}", operation_id="delete_image")
async def delete_image(
    image_name: str = Path(description="The name of the image to delete"),
) -> None:
    """Deletes an image"""

    try:
        ApiDependencies.invoker.services.images.delete(image_name)
    except Exception:
        # TOD0O: Does this need any exception handling at all?
        pass


@images_router.delete("/intermediates", operation_id="clear_intermediates")
async def clear_intermediates() -> int:
    """Clears all intermediates"""

    try:
        count_deleted = ApiDependencies.invoker.services.images.delete_intermediates()
        return count_deleted
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to clear intermediates")
        pass


@images_router.get("/intermediates", operation_id="get_intermediates_count")
async def get_intermediates_count() -> int:
    """Gets the count of intermediate images"""

    try:
        return ApiDependencies.invoker.services.images.get_intermediates_count()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get intermediates")
        pass


@images_router.patch(
    "/i/{image_name}",
    operation_id="update_image",
    response_model=ImageDTO,
)
async def update_image(
    image_name: str = Path(description="The name of the image to update"),
    image_changes: ImageRecordChanges = Body(description="The changes to apply to the image"),
) -> ImageDTO:
    """Updates an image"""

    try:
        return ApiDependencies.invoker.services.images.update(image_name, image_changes)
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to update image")


@images_router.get(
    "/i/{image_name}",
    operation_id="get_image_dto",
    response_model=ImageDTO,
)
async def get_image_dto(
    image_name: str = Path(description="The name of image to get"),
) -> ImageDTO:
    """Gets an image's DTO"""

    try:
        return ApiDependencies.invoker.services.images.get_dto(image_name)
    except Exception:
        raise HTTPException(status_code=404)


@images_router.get(
    "/i/{image_name}/metadata",
    operation_id="get_image_metadata",
    response_model=Optional[MetadataField],
)
async def get_image_metadata(
    image_name: str = Path(description="The name of image to get"),
) -> Optional[MetadataField]:
    """Gets an image's metadata"""

    try:
        return ApiDependencies.invoker.services.images.get_metadata(image_name)
    except Exception:
        raise HTTPException(status_code=404)


@images_router.get(
    "/i/{image_name}/workflow", operation_id="get_image_workflow", response_model=Optional[WorkflowWithoutID]
)
async def get_image_workflow(
    image_name: str = Path(description="The name of image whose workflow to get"),
) -> Optional[WorkflowWithoutID]:
    try:
        return ApiDependencies.invoker.services.images.get_workflow(image_name)
    except Exception:
        raise HTTPException(status_code=404)


@images_router.api_route(
    "/i/{image_name}/full",
    methods=["GET", "HEAD"],
    operation_id="get_image_full",
    response_class=Response,
    responses={
        200: {
            "description": "Return the full-resolution image",
            "content": {"image/png": {}},
        },
        404: {"description": "Image not found"},
    },
)
async def get_image_full(
    image_name: str = Path(description="The name of full-resolution image file to get"),
) -> FileResponse:
    """Gets a full-resolution image file"""

    try:
        path = ApiDependencies.invoker.services.images.get_path(image_name)

        if not ApiDependencies.invoker.services.images.validate_path(path):
            raise HTTPException(status_code=404)

        response = FileResponse(
            path,
            media_type="image/png",
            filename=image_name,
            content_disposition_type="inline",
        )
        response.headers["Cache-Control"] = f"max-age={IMAGE_MAX_AGE}"
        return response
    except Exception:
        raise HTTPException(status_code=404)


@images_router.get(
    "/i/{image_name}/thumbnail",
    operation_id="get_image_thumbnail",
    response_class=Response,
    responses={
        200: {
            "description": "Return the image thumbnail",
            "content": {"image/webp": {}},
        },
        404: {"description": "Image not found"},
    },
)
async def get_image_thumbnail(
    image_name: str = Path(description="The name of thumbnail image file to get"),
) -> FileResponse:
    """Gets a thumbnail image file"""

    try:
        path = ApiDependencies.invoker.services.images.get_path(image_name, thumbnail=True)
        if not ApiDependencies.invoker.services.images.validate_path(path):
            raise HTTPException(status_code=404)

        response = FileResponse(path, media_type="image/webp", content_disposition_type="inline")
        response.headers["Cache-Control"] = f"max-age={IMAGE_MAX_AGE}"
        return response
    except Exception:
        raise HTTPException(status_code=404)


@images_router.get(
    "/i/{image_name}/urls",
    operation_id="get_image_urls",
    response_model=ImageUrlsDTO,
)
async def get_image_urls(
    image_name: str = Path(description="The name of the image whose URL to get"),
) -> ImageUrlsDTO:
    """Gets an image and thumbnail URL"""

    try:
        image_url = ApiDependencies.invoker.services.images.get_url(image_name)
        thumbnail_url = ApiDependencies.invoker.services.images.get_url(image_name, thumbnail=True)
        return ImageUrlsDTO(
            image_name=image_name,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
        )
    except Exception:
        raise HTTPException(status_code=404)


@images_router.get(
    "/",
    operation_id="list_image_dtos",
    response_model=OffsetPaginatedResults[ImageDTO],
)
async def list_image_dtos(
    image_origin: Optional[ResourceOrigin] = Query(default=None, description="The origin of images to list."),
    categories: Optional[list[ImageCategory]] = Query(default=None, description="The categories of image to include."),
    is_intermediate: Optional[bool] = Query(default=None, description="Whether to list intermediate images."),
    board_id: Optional[str] = Query(
        default=None,
        description="The board id to filter by. Use 'none' to find images without a board.",
    ),
    offset: int = Query(default=0, description="The page offset"),
    limit: int = Query(default=10, description="The number of images per page"),
) -> OffsetPaginatedResults[ImageDTO]:
    """Gets a list of image DTOs"""

    image_dtos = ApiDependencies.invoker.services.images.get_many(
        offset,
        limit,
        image_origin,
        categories,
        is_intermediate,
        board_id,
    )

    return image_dtos


class DeleteImagesFromListResult(BaseModel):
    deleted_images: list[str]


@images_router.post("/delete", operation_id="delete_images_from_list", response_model=DeleteImagesFromListResult)
async def delete_images_from_list(
    image_names: list[str] = Body(description="The list of names of images to delete", embed=True),
) -> DeleteImagesFromListResult:
    try:
        deleted_images: list[str] = []
        for image_name in image_names:
            try:
                ApiDependencies.invoker.services.images.delete(image_name)
                deleted_images.append(image_name)
            except Exception:
                pass
        return DeleteImagesFromListResult(deleted_images=deleted_images)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete images")


class ImagesUpdatedFromListResult(BaseModel):
    updated_image_names: list[str] = Field(description="The image names that were updated")


@images_router.post("/star", operation_id="star_images_in_list", response_model=ImagesUpdatedFromListResult)
async def star_images_in_list(
    image_names: list[str] = Body(description="The list of names of images to star", embed=True),
) -> ImagesUpdatedFromListResult:
    try:
        updated_image_names: list[str] = []
        for image_name in image_names:
            try:
                ApiDependencies.invoker.services.images.update(image_name, changes=ImageRecordChanges(starred=True))
                updated_image_names.append(image_name)
            except Exception:
                pass
        return ImagesUpdatedFromListResult(updated_image_names=updated_image_names)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to star images")


@images_router.post("/unstar", operation_id="unstar_images_in_list", response_model=ImagesUpdatedFromListResult)
async def unstar_images_in_list(
    image_names: list[str] = Body(description="The list of names of images to unstar", embed=True),
) -> ImagesUpdatedFromListResult:
    try:
        updated_image_names: list[str] = []
        for image_name in image_names:
            try:
                ApiDependencies.invoker.services.images.update(image_name, changes=ImageRecordChanges(starred=False))
                updated_image_names.append(image_name)
            except Exception:
                pass
        return ImagesUpdatedFromListResult(updated_image_names=updated_image_names)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to unstar images")


class ImagesDownloaded(BaseModel):
    response: Optional[str] = Field(
        description="If defined, the message to display to the user when images begin downloading"
    )


@images_router.post("/download", operation_id="download_images_from_list", response_model=ImagesDownloaded)
async def download_images_from_list(
    image_names: list[str] = Body(description="The list of names of images to download", embed=True),
    board_id: Optional[str] = Body(
        default=None, description="The board from which image should be downloaded from", embed=True
    ),
) -> ImagesDownloaded:
    # return ImagesDownloaded(response="Your images are downloading")
    raise HTTPException(status_code=501, detail="Endpoint is not yet implemented")
